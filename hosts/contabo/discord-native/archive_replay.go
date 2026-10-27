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

 "github.com/bwmarrin/discordgo"
)

var contaboReplayMutex sync.Mutex

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
  rows, err := tx.Query(`SELECT id,json FROM messages WHERE channel_id=? AND
    (length(id)>length(?) OR (length(id)=length(?) AND id>?))
    ORDER BY length(id),id LIMIT 100`, channel,after,after,after)
  if err != nil { return err }
  messages := make([]*discordgo.Message,0,100)
  for rows.Next() {
   var ident,raw string; if err = rows.Scan(&ident,&raw); err != nil { rows.Close(); return err }
   var msg discordgo.Message
   if err = json.Unmarshal([]byte(raw),&msg); err != nil { rows.Close(); return err }
   if msg.ID != ident || msg.ChannelID != channel || msg.Author == nil { rows.Close(); return fmt.Errorf("invalid archive message identity") }
   messages = append(messages,&msg)
  }
  err=rows.Err(); rows.Close(); if err != nil { return err }
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
