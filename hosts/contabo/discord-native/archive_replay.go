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
 started,failed:=0,0
 pilot:=os.Getenv("CONTABO_DISCORD_PILOT_FILE")!=""
 for _,c:=range channels {
  if pilot && c.kind!="dms" {continue}
  meta,err:=user.Session.Channel(c.id)
  if err!=nil {failed++;continue} // Never bypass an inaccessible source scope.
  portal:=user.GetPortalByMeta(meta)
  if err=portal.CreateMatrixRoom(user,meta);err!=nil {failed++;continue}
  started++
  if pilot {break}
 }
 jsonResponse(w,200,map[string]int{"portals_started":started,"source_or_portal_failures":failed})
}

// Called only while the portal's native forward-backfill lock is held. The
// same gate covers fresh rooms, process restart and incoming live traffic.
func (portal *Portal) ensureContaboArchive(source *User, thread *Thread) {
 if os.Getenv("CONTABO_DISCORD_ARCHIVE")=="" || portal.contaboArchiveReady { return }
 contaboReplayMutex.Lock(); defer contaboReplayMutex.Unlock()
 if err:=portal.replayContaboArchive(source,thread); err!=nil { panic(err) }
 portal.contaboArchiveReady=true
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
 if err == sql.ErrNoRows { return nil }; if err != nil { return err }
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
   switch msg.Type {
   case discordgo.MessageTypeChannelNameChange,discordgo.MessageTypeChannelIconChange,discordgo.MessageTypeChannelPinnedMessage:
    // These source events are handled by native channel metadata, not messages.
   default:
    if firstBridgeable {
     firstBridgeable=false
     if len(portal.bridge.DB.Message.GetByDiscordID(portal.Key,msg.ID))==0 && portal.bridge.DB.Message.GetLast(portal.Key)!=nil {
      return fmt.Errorf("existing nonempty room cannot accept older archive; fresh portal required")
     }
    }
    portal.handleDiscordMessageCreate(source,msg,thread)
    if len(portal.bridge.DB.Message.GetByDiscordID(portal.Key,msg.ID))==0 { return fmt.Errorf("archived message was not mapped; cutover refused") }
   }
   after=msg.ID
  }
 }
 // The caller still holds the native forward-backfill lock. Fetch messages
 // since the frozen archive waterline before allowing queued live delivery.
 if after!="" { return portal.backfillUnlimitedMissed(portal.log,source,after,thread) }
 return nil
}

func contaboArchiveBatch(tx *sql.Tx,channel,after string) ([]*discordgo.Message,error) {
 rows, err := tx.Query(`SELECT id,json FROM messages WHERE channel_id=? AND
    (length(id)>length(?) OR (length(id)=length(?) AND id>?))
    ORDER BY length(id),id LIMIT 100`, channel,after,after,after)
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
