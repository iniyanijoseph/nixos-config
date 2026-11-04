package connector

// A legacy email portal is an independent Matrix room. Matrix has no operation
// to move those events into another room. Replay the *source* mail through the
// native bridge and then mark the old room as archived only when every native
// email message/part that we can identify has a real contact-room mapping.
// Keep the old room and events; an IMAP folder may omit deleted/archived mail.
import (
 "context"
 "database/sql"
 "errors"
 "strings"
 "sync"
 "time"

 "maunium.net/go/mautrix/bridgev2"
 "maunium.net/go/mautrix/bridgev2/networkid"
 "maunium.net/go/mautrix/event"
)

var contaboLegacyRun sync.Map

type legacyCoverage struct {
 Total int
 Mapped int
 ContactRoomIDs map[networkid.PortalID]bool
}

func (c legacyCoverage) complete() bool {
 return c.Total > 0 && c.Total == c.Mapped && len(c.ContactRoomIDs) > 0
}

// This is deliberately read-only: do not conflate an imported email with a
// complete source-Matrix-event/attachment migration.
func(ec *EmailConnector) legacyCoverageFor(ctx context.Context, portal *bridgev2.Portal) (legacyCoverage,error){
 return legacyCoverageForDB(ctx,ec.Bridge.DB.RawDB,string(ec.Bridge.DB.BridgeID),string(portal.ID),string(portal.Receiver))
}

func legacyCoverageForDB(ctx context.Context,db *sql.DB,bridgeID,portalID,receiver string)(legacyCoverage,error){
 result:=legacyCoverage{ContactRoomIDs:make(map[networkid.PortalID]bool)}
 rows,err:=db.QueryContext(ctx,`SELECT o.id,
     COUNT(DISTINCT o.part_id) AS old_parts,
     COUNT(DISTINCT CASE WHEN n.mxid IS NOT NULL AND n.mxid != '' AND n.mxid NOT LIKE '~fake:%'
         THEN n.part_id END) AS new_parts,
     MIN(CASE WHEN n.mxid IS NOT NULL AND n.mxid != '' AND n.mxid NOT LIKE '~fake:%'
         THEN n.room_id END) AS first_room,
     MAX(CASE WHEN n.mxid IS NOT NULL AND n.mxid != '' AND n.mxid NOT LIKE '~fake:%'
         THEN n.room_id END) AS last_room
   FROM message o LEFT JOIN message n
     ON n.bridge_id=o.bridge_id AND n.room_receiver=o.room_receiver
       AND n.id='contact-email:' || substr(o.id,7) AND n.room_id LIKE 'contact:%'
   WHERE o.bridge_id=$1 AND o.room_id=$2 AND o.room_receiver=$3
     AND o.id LIKE 'email:%' AND o.mxid IS NOT NULL AND o.mxid != ''
     AND o.mxid NOT LIKE '~fake:%'
   GROUP BY o.id`, bridgeID,portalID,receiver)
 if err!=nil{return result,err}
 defer rows.Close()
 for rows.Next(){
  var raw string
  var oldParts,newParts int
  var first,last *string
  if err=rows.Scan(&raw,&oldParts,&newParts,&first,&last);err!=nil{return result,err}
  result.Total++
  if oldParts<1 || newParts<oldParts || first==nil || last==nil || *first!=*last {continue}
  result.Mapped++
  result.ContactRoomIDs[networkid.PortalID(*first)]=true
 }
 return result,rows.Err()
}

func(ec *EmailConnector) legacyPortalsFor(ctx context.Context, login *bridgev2.UserLogin)([]*bridgev2.Portal,error){
 portals,err:=ec.Bridge.GetAllPortalsWithMXID(ctx)
 if err!=nil{return nil,err}
 var out []*bridgev2.Portal
 for _,portal:=range portals{
  if portal.Receiver==login.ID && strings.HasPrefix(string(portal.ID),"thread:"){
   out=append(out,portal)
  }
 }
 return out,nil
}

func(ec *EmailConnector) finalizeLegacyConsolidation(ctx context.Context, login *bridgev2.UserLogin)(int,int,error){
 portals,err:=ec.legacyPortalsFor(ctx,login);if err!=nil{return 0,0,err}
 // A durable record avoids repeatedly changing state in an already retired
 // room when the bridge or launcher restarts.
 _,err=ec.Bridge.DB.Exec(ctx,`CREATE TABLE IF NOT EXISTS contabo_legacy_mail_retirement (
   bridge_id TEXT NOT NULL, receiver TEXT NOT NULL, portal_id TEXT NOT NULL,
   contact_rooms TEXT NOT NULL, retired_at BIGINT NOT NULL,
   PRIMARY KEY (bridge_id,receiver,portal_id))`)
 if err!=nil{return 0,0,err}
 complete:=0
 for _,portal:=range portals{
  if err=ctx.Err();err!=nil{return complete,len(portals),err}
  var previous string
  err=ec.Bridge.DB.QueryRow(ctx,`SELECT contact_rooms FROM contabo_legacy_mail_retirement
     WHERE bridge_id=$1 AND receiver=$2 AND portal_id=$3`,
    ec.Bridge.DB.BridgeID,portal.Receiver,portal.ID).Scan(&previous)
  if err==nil{complete++;continue}
  // A missing marker is normal. Any other database error is not.
  if err!=nil && !errors.Is(err,sql.ErrNoRows){return complete,len(portals),err}
  coverage,err:=ec.legacyCoverageFor(ctx,portal)
  if err!=nil{return complete,len(portals),err}
  if !coverage.complete() || len(coverage.ContactRoomIDs)>8{continue}
  var links []string
  for target:=range coverage.ContactRoomIDs {
   contact,err:=ec.Bridge.GetExistingPortalByKey(ctx,networkid.PortalKey{ID:target,Receiver:login.ID})
   if err!=nil{return complete,len(portals),err}
   if contact==nil || contact.MXID==""{links=nil;break}
   links=append(links,contact.MXID.URI().MatrixToURL())
  }
  if len(links)==0{continue}
  // Retire in place, rather than deleting, redacting or force-leaving rooms.
  // Do not replace custom room names, and do not change non-email portals.
  topic:="Archived email conversation — copied to contact room(s): "+strings.Join(links," ")
  if _,err=ec.Bridge.Bot.SendState(ctx,portal.MXID,event.StateTopic,"",
    &event.Content{Parsed:&event.TopicEventContent{Topic:topic}},time.Time{});err!=nil{return complete,len(portals),err}
  if !portal.NameIsCustom && !strings.HasPrefix(portal.Name,"Archived email · "){
   name:="Archived email · "+portal.Name
   if len([]rune(name))>220{name=string([]rune(name)[:220])}
   if _,err=ec.Bridge.Bot.SendState(ctx,portal.MXID,event.StateRoomName,"",
     &event.Content{Parsed:&event.RoomNameEventContent{Name:name}},time.Time{});err!=nil{return complete,len(portals),err}
  }
  _,err=ec.Bridge.DB.Exec(ctx,`INSERT INTO contabo_legacy_mail_retirement
     (bridge_id,receiver,portal_id,contact_rooms,retired_at) VALUES ($1,$2,$3,$4,$5)
     ON CONFLICT (bridge_id,receiver,portal_id) DO NOTHING`,
    ec.Bridge.DB.BridgeID,portal.Receiver,portal.ID,strings.Join(links," "),time.Now().Unix())
  if err!=nil{return complete,len(portals),err}
  complete++
 }
 return complete,len(portals),nil
}

func(ec *EmailConnector) autoConsolidateLegacy(client *EmailClient){
 if client==nil || client.UserLogin==nil || ec.Contacts==nil{return}
 ctx:=client.ctx
 // Replay uses a separate read-only IMAP socket; live IDLE readiness is not required.
 portals,err:=ec.legacyPortalsFor(ctx,client.UserLogin)
 if err!=nil{client.UserLogin.Log.Error().Err(err).Msg("Legacy email portal audit failed");return}
 if len(portals)==0{client.UserLogin.Log.Info().Msg("Email consolidation: no legacy per-subject rooms found");return}
 if client.IMAPClient==nil{client.UserLogin.Log.Warn().Int("legacy_rooms",len(portals)).Msg("Email consolidation blocked: no IMAP account; old rooms preserved");return}
 key:=string(client.UserLogin.ID)
 if _,busy:=contaboMailJobs.LoadOrStore(key,true);busy{client.UserLogin.Log.Info().Msg("Email consolidation deferred: another backfill running");return}
 defer contaboMailJobs.Delete(key)
 if _,busy:=contaboLegacyRun.LoadOrStore(key,true);busy{return}
 defer contaboLegacyRun.Delete(key)
 folders:=append([]string(nil),client.MonitoredFolders...)
 if len(folders)==0{folders=[]string{"INBOX"}}
 client.UserLogin.Log.Info().Int("legacy_rooms",len(portals)).Strs("selected_folders",folders).
    Msg("Starting independent IMAP replay into consolidated contact rooms")
 total,err:=client.IMAPClient.ContaboBackfill(ctx,folders,0,nil)
 if err!=nil{
  client.UserLogin.Log.Error().Err(err).Int("processed",total).
    Msg("Contact-room migration paused; source rooms preserved; resume with !matrimail backfill all")
  return
 }
 archived,seen,err:=ec.finalizeLegacyConsolidation(ctx,client.UserLogin)
 if err!=nil{client.UserLogin.Log.Error().Err(err).Msg("Legacy email room retirement paused");return}
 client.UserLogin.Log.Info().Int("processed",total).Int("archived_rooms",archived).
   Int("legacy_rooms",seen).Msg("Contact-room replay and legacy coverage audit finished")
 if archived<seen{client.UserLogin.Log.Warn().Int("unverified_rooms",seen-archived).
   Msg("Legacy rooms remain unchanged where selected IMAP folders lack complete source coverage")}
}

func(ec *EmailConnector) startAutoConsolidation(client *EmailClient){
 if ec.Contacts==nil{return}
 go ec.autoConsolidateLegacy(client)
}

