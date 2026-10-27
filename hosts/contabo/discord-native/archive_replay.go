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
 started,failed,ready:=0,0,0
 pilot:=os.Getenv("CONTABO_DISCORD_PILOT_FILE")!=""
 for _,c:=range channels {
  if pilot && c.kind!="dms" {continue}
  meta,err:=user.Session.Channel(c.id)
  if err!=nil {failed++;continue} // Never bypass an inaccessible source scope.
  portal:=user.GetPortalByMeta(meta)
  if err=portal.CreateMatrixRoom(user,meta);err!=nil {failed++;continue}
  started++
  if portal.forwardBackfillLock.TryLock() {
   if portal.contaboArchiveReady[portal.Key.ChannelID] {ready++}
   portal.forwardBackfillLock.Unlock()
  }
  if pilot {break}
 }
 jsonResponse(w,200,map[string]int{"portals_started":started,"portals_ready":ready,"source_or_portal_failures":failed})
}

// Called only while the portal's native forward-backfill lock is held. The
// same gate covers fresh rooms, process restart and incoming live traffic.
func (portal *Portal) ensureContaboArchive(source *User, thread *Thread) {
 if os.Getenv("CONTABO_DISCORD_ARCHIVE")=="" { return }
 channel:=portal.Key.ChannelID
 if thread!=nil {channel=thread.ID}
 if portal.contaboArchiveReady==nil {portal.contaboArchiveReady=make(map[string]bool)}
 if portal.contaboArchiveReady[channel] {return}
 contaboReplayMutex.Lock(); defer contaboReplayMutex.Unlock()
 if err:=portal.replayContaboArchive(source,thread); err!=nil { panic(err) }
 if thread==nil {
  intent:=portal.MainIntent()
  var levels map[string]interface{}
  if err:=intent.StateEvent(portal.MXID,event.StatePowerLevels,"",&levels);err!=nil {panic(err)}
  if users,ok:=levels["users"].(map[string]interface{});ok && users["@me:iniyanjoseph.com"]==float64(-1) {
   users["@me:iniyanjoseph.com"]=0
   if _,err:=intent.SendStateEvent(portal.MXID,event.StatePowerLevels,"",levels);err!=nil {panic(err)}
   if _,err:=intent.SendStateEvent(portal.MXID,event.StateTopic,"",map[string]string{"topic":portal.Topic});err!=nil {panic(err)}
  }
 }
 portal.contaboArchiveReady[channel]=true
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
    // the authenticated message endpoint without replacing archived text or
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
 current,err:=source.Session.ChannelMessage(msg.ChannelID,msg.ID)
 if err!=nil {return fmt.Errorf("archive attachment URL refresh failed: %w",err)}
 if current.ID!=msg.ID || current.ChannelID!=msg.ChannelID {return fmt.Errorf("attachment refresh returned a different message")}
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
