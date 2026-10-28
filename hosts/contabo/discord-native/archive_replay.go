package main

// Feed the local archive through the pinned bridge's native converter. No
// Synapse SQL writes, synthesized event IDs or second set of portal mappings.
import (
 "database/sql"
 "encoding/json"
 "fmt"
 "net/url"
 "os"
 "strings"
 "sync"
 "net/http"

 "github.com/bwmarrin/discordgo"
 "maunium.net/go/mautrix/event"
)

var contaboReplayMutex sync.Mutex
var contaboPilotMutex sync.Mutex

func (portal *Portal) contaboPilotAllowed() bool {
 path:=os.Getenv("CONTABO_DISCORD_PILOT_FILE")
 if path=="" { return true }
 if portal.Type!=discordgo.ChannelTypeDM { return false }
 uri:=(&url.URL{Scheme:"file",Path:os.Getenv("CONTABO_DISCORD_ARCHIVE"),RawQuery:"mode=ro"}).String()
 db,err:=sql.Open("sqlite3",uri);if err!=nil {return false};defer db.Close()
 var count int
 if err=db.QueryRow("SELECT count(*) FROM channels WHERE id=? AND kind='dms' AND complete=1 AND EXISTS(SELECT 1 FROM messages WHERE channel_id=?)",portal.Key.ChannelID,portal.Key.ChannelID).Scan(&count);err!=nil || count!=1 {return false}
 contaboPilotMutex.Lock(); defer contaboPilotMutex.Unlock()
 data,err:=os.ReadFile(path)
 if err==nil { return strings.TrimSpace(string(data))==portal.Key.ChannelID }
 if !os.IsNotExist(err) { return false }
 // Persist the first pilot choice before creating any Matrix room.
 f,err:=os.OpenFile(path,os.O_CREATE|os.O_EXCL|os.O_WRONLY,0600)
 if err!=nil { return false }
 _,err=f.WriteString(portal.Key.ChannelID+"\n")
 if err==nil { err=f.Sync() }; f.Close()
 return err==nil
}

func (p *ProvisioningAPI) contaboStartArchive(w http.ResponseWriter,r *http.Request) {
 user:=r.Context().Value("user").(*User)
 if !user.Connected() { jsonResponse(w,409,map[string]string{"error":"Discord login required"}); return }
 uri:=(&url.URL{Scheme:"file",Path:os.Getenv("CONTABO_DISCORD_ARCHIVE"),RawQuery:"mode=ro"}).String()
 db,err:=sql.Open("sqlite3",uri); if err!=nil {jsonResponse(w,500,map[string]string{"error":"Archive unavailable"});return}; defer db.Close()
 query:=`SELECT c.id,c.kind,count(m.id) FROM channels c JOIN messages m ON m.channel_id=c.id
   WHERE c.complete=1 AND (c.kind='dms' OR c.kind='guild:804408079940583475')
   GROUP BY c.id,c.kind ORDER BY count(m.id),length(c.id),c.id`
 rows,err:=db.Query(query);if err!=nil {jsonResponse(w,500,map[string]string{"error":"Archive inventory failed"});return}
 type channel struct{id,kind string};channels:=[]channel{}
 for rows.Next(){var c channel;var n int;if rows.Scan(&c.id,&c.kind,&n)!=nil {rows.Close();jsonResponse(w,500,map[string]string{"error":"Archive inventory invalid"});return};channels=append(channels,c)}
 err=rows.Err();rows.Close();if err!=nil {jsonResponse(w,500,map[string]string{"error":"Archive inventory incomplete"});return}
 started,failed,ready,blocked:=0,0,0,0
 pilot:=os.Getenv("CONTABO_DISCORD_PILOT_FILE")!=""
 for _,c:=range channels {
  if pilot && c.kind!="dms" {continue}
  meta,err:=user.Session.Channel(c.id)
  if err!=nil {failed++;continue} // Never bypass an inaccessible source scope.
  portal:=user.GetPortalByMeta(meta)
  if err=portal.CreateMatrixRoom(user,meta);err!=nil {failed++;continue}
  started++
  if portal.forwardBackfillLock.TryLock() {
   if portal.contaboArchiveErrors[portal.Key.ChannelID]!="" {blocked++}
   if portal.contaboArchiveReady[portal.Key.ChannelID] {
    ready++;portal.forwardBackfillLock.Unlock()
   } else {
    // Existing rooms also resume after process restart, including idle DMs.
    // forwardBackfillInitial takes ownership of this already-held lock.
    go portal.forwardBackfillInitial(user,nil)
   }
  }
  if pilot {break}
 }
 jsonResponse(w,200,map[string]int{"portals_started":started,"portals_ready":ready,"portals_blocked":blocked,"source_or_portal_failures":failed})
}

// The caller holds forwardBackfillLock. Failed media/conversion leaves the
// room gated and its mappings intact, without terminating other room workers.
func (portal *Portal) completeContaboArchive(channel string, replay func() error) (ready bool) {
 defer func() {
  if failure:=recover(); failure!=nil {
   portal.contaboArchiveFailed(channel,fmt.Errorf("archive replay panic: %v",failure))
   ready=false
  }
 }()
 if err:=replay(); err!=nil {
  portal.contaboArchiveFailed(channel,err)
  return false
 }
 if portal.contaboArchiveReady==nil {portal.contaboArchiveReady=make(map[string]bool)}
 portal.contaboArchiveReady[channel]=true
 delete(portal.contaboArchiveErrors,channel)
 return true
}

func (portal *Portal) contaboArchiveFailed(channel string,err error) {
 if portal.contaboArchiveErrors==nil {portal.contaboArchiveErrors=make(map[string]string)}
 portal.contaboArchiveErrors[channel]=err.Error()
 delete(portal.contaboArchiveReady,channel)
 portal.log.Error().Err(err).Str("archive_channel_id",channel).
  Msg("Discord archive import blocked for this room; other rooms may continue")
}

// Called only while the portal's native forward-backfill lock is held. The
// same gate covers fresh rooms, process restart and incoming live traffic.
func (portal *Portal) ensureContaboArchive(source *User, thread *Thread) bool {
 if os.Getenv("CONTABO_DISCORD_ARCHIVE")=="" { return true }
 channel:=portal.Key.ChannelID
 if thread!=nil {channel=thread.ID}
 if portal.contaboArchiveReady==nil {portal.contaboArchiveReady=make(map[string]bool)}
 if portal.contaboArchiveReady[channel] {return true}
 contaboReplayMutex.Lock(); defer contaboReplayMutex.Unlock()
 return portal.completeContaboArchive(channel,func() error {
 if err:=portal.replayContaboArchive(source,thread); err!=nil { return err }
 if thread==nil {
  intent:=portal.MainIntent()
  var levels map[string]interface{}
  if err:=intent.StateEvent(portal.MXID,event.StatePowerLevels,"",&levels);err!=nil {return err}
  if users,ok:=levels["users"].(map[string]interface{});ok && users["@me:iniyanjoseph.com"]==float64(-1) {
   users["@me:iniyanjoseph.com"]=0
   // Clear the import topic before enabling sends, so a failed state update
   // cannot leave an incomplete room writable.
   if _,err:=intent.SendStateEvent(portal.MXID,event.StateTopic,"",map[string]string{"topic":portal.Topic});err!=nil {return err}
   if _,err:=intent.SendStateEvent(portal.MXID,event.StatePowerLevels,"",levels);err!=nil {return err}
  }
 }
 return nil
 })
}

func (portal *Portal) replayContaboArchive(source *User, thread *Thread) error {
 path := os.Getenv("CONTABO_DISCORD_ARCHIVE")
 if path == "" { return nil }
 channel := portal.Key.ChannelID
 if thread != nil { channel = thread.ID }
 uri := (&url.URL{Scheme:"file", Path:path, RawQuery:"mode=ro"}).String()
 db, err := sql.Open("sqlite3", uri)
 if err != nil { return err }; defer db.Close()
 tx, err := db.Begin(); if err != nil { return err }; defer tx.Rollback()
 var kind string; var complete int
 err = tx.QueryRow("SELECT kind,complete FROM channels WHERE id=?", channel).Scan(&kind,&complete)
 if err == sql.ErrNoRows {
  switch portal.Type {
  case discordgo.ChannelTypeDM,discordgo.ChannelTypeGroupDM,discordgo.ChannelTypeGuildText,discordgo.ChannelTypeGuildNews:
   return portal.backfillUnlimitedMissed(portal.log,source,"0",thread)
  default:return nil
  }
 }; if err != nil { return err }
 allowed := kind == "dms" || kind == "guild:804408079940583475" || kind == "threads-active:804408079940583475"
 if strings.HasPrefix(kind,"archived-public:") || strings.HasPrefix(kind,"archived-private:") {
  parent := strings.SplitN(kind,":",2)[1]; var count int
  if err = tx.QueryRow("SELECT count(*) FROM channels WHERE id=? AND kind='guild:804408079940583475'",parent).Scan(&count); err != nil { return err }; allowed = count == 1
 }
 if !allowed { return nil }; if complete != 1 { return fmt.Errorf("archive channel is incomplete") }
 var after string
 firstBridgeable:=true
 for {
  messages,err:=contaboArchiveBatch(tx,channel,after)
  if err!=nil { return err }
  if len(messages)==0 { break }
  for _,msg := range messages {
    if firstBridgeable {
     firstBridgeable=false
     if len(portal.bridge.DB.Message.GetByDiscordID(portal.Key,msg.ID))==0 && portal.bridge.DB.Message.GetLast(portal.Key)!=nil {
      return fmt.Errorf("existing nonempty room cannot accept older archive; fresh portal required")
     }
    }
    // Takeout-time CDN signatures can expire before import. Refresh URLs via
    // authenticated channel history without replacing archived text or
    // accepting a different attachment identity/size.
    if len(portal.bridge.DB.Message.GetByDiscordID(portal.Key,msg.ID))==0 {
     if err:=contaboRefreshAttachments(source,msg);err!=nil {return fmt.Errorf("archived message %s: %w",msg.ID,err)}
    }
    portal.handleDiscordMessageCreate(source,contaboArchiveMessage(msg),thread,int(msg.Type))
    if len(portal.bridge.DB.Message.GetByDiscordID(portal.Key,msg.ID))==0 { return fmt.Errorf("archived message %s was not mapped; cutover refused",msg.ID) }
   after=msg.ID
  }
 }
 // The caller still holds the native forward-backfill lock. Fetch messages
 // since the frozen archive waterline before allowing queued live delivery.
 if after!="" { return portal.backfillUnlimitedMissed(portal.log,source,after,thread) }
 return nil
}

func contaboArchiveMessage(msg *discordgo.Message) *discordgo.Message {
 switch int(msg.Type) {case 0,3,7,19,20,23:return msg}
 copy:=*msg
 copy.Type=discordgo.MessageTypeDefault
 descriptions:=map[int]string{1:"Added a recipient.",2:"Removed a recipient.",
  4:"Changed the channel name.",5:"Changed the channel icon.",6:"Pinned a Discord message.",
  8:"Boosted the server.",9:"Server boost level changed.",10:"Server boost level changed.",
  11:"Server boost level changed.",18:"Created a Discord thread.",21:"Discord thread starter.",
  22:"Discord server invitation reminder.",24:"Discord moderation event."}
 description,ok:=descriptions[int(msg.Type)];if !ok {description="Discord system event."}
 copy.Content=description
 if msg.Content!="" {copy.Content+="\n"+msg.Content}
 return &copy
}

func contaboRefreshAttachments(source *User,msg *discordgo.Message) error {
 if len(msg.Attachments)==0 {return nil}
 // The single-message endpoint rejects user sessions with Discord error
 // 20002 ("Only bots can use this endpoint"). Read the history window around
 // the archived ID and require the exact message before accepting any URLs.
 messages,err:=source.Session.ChannelMessages(msg.ChannelID,1,"","",msg.ID)
 if err!=nil {return fmt.Errorf("archive attachment URL refresh failed: %w",err)}
 var current *discordgo.Message
 for _,candidate:=range messages {
  if candidate!=nil && candidate.ID==msg.ID && candidate.ChannelID==msg.ChannelID {current=candidate;break}
 }
 if current==nil {return fmt.Errorf("attachment refresh did not return the archived message; original archive retained")}
 for _,old:=range msg.Attachments {
  found:=false
  for _,fresh:=range current.Attachments {
   if fresh.ID==old.ID && fresh.Size==old.Size && fresh.URL!="" {
    old.URL=fresh.URL;old.ProxyURL=fresh.ProxyURL;found=true;break
   }
  }
  if !found {return fmt.Errorf("archived attachment no longer available; original archive retained")}
 }
 return nil
}

func contaboArchiveBatch(tx *sql.Tx,channel,after string) ([]*discordgo.Message,error) {
 rows, err := tx.Query(`SELECT id,json FROM messages WHERE channel_id=? AND
    (length(id),id)>(length(?),?)
    ORDER BY length(id),id LIMIT 100`, channel,after,after)
  if err != nil { return nil,err }
  messages := make([]*discordgo.Message,0,100)
  for rows.Next() {
   var ident,raw string; if err = rows.Scan(&ident,&raw); err != nil { rows.Close(); return nil,err }
   var msg discordgo.Message
   if err = json.Unmarshal([]byte(raw),&msg); err != nil { rows.Close(); return nil,err }
   if msg.ID != ident || msg.ChannelID != channel || msg.Author == nil { rows.Close(); return nil,fmt.Errorf("invalid archive message identity") }
   messages = append(messages,&msg)
  }
  err=rows.Err(); rows.Close(); if err != nil { return nil,err }
 return messages,nil
}
