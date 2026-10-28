package main

import (
 "database/sql"
 "encoding/json"
 "testing"
 "net/http"
 "io"
 "strings"
 "errors"
 "github.com/bwmarrin/discordgo"
)

type contaboTransport func(*http.Request)(*http.Response,error)
func(f contaboTransport)RoundTrip(r *http.Request)(*http.Response,error){return f(r)}

func TestContaboArchiveRefreshKeepsArchivedTextAndChecksMedia(t *testing.T) {
 session,err:=discordgo.New("fixture-user-token");if err!=nil {t.Fatal(err)}
 if !session.IsUser {t.Fatal("refresh regression must exercise a user session")}
 session.Client=&http.Client{Transport:contaboTransport(func(r *http.Request)(*http.Response,error){
  if !strings.HasSuffix(r.URL.Path,"/channels/123/messages") {
   // Reproduce Discord's bot-only single-message endpoint restriction.
   return &http.Response{StatusCode:403,Header:make(http.Header),Body:io.NopCloser(strings.NewReader(`{"message":"Only bots can use this endpoint","code":20002}`))},nil
  }
  if r.Method!="GET" || r.URL.Query().Get("around")!="100" || r.URL.Query().Get("limit")!="1" {t.Fatalf("wrong history request: %s %s",r.Method,r.URL)}
  if r.Header.Get("Authorization")!="fixture-user-token" {t.Fatal("user credentials changed")}
  return &http.Response{StatusCode:200,Header:make(http.Header),Body:io.NopCloser(strings.NewReader(`[{"id":"100","channel_id":"123","content":"changed online","attachments":[{"id":"456","size":12,"url":"https://cdn.discordapp.com/fresh"}]}]`))},nil
 })}
 source:=&User{Session:session}
 msg:=&discordgo.Message{ID:"100",ChannelID:"123",Content:"archived text",Attachments:[]*discordgo.MessageAttachment{{ID:"456",Size:12,URL:"https://cdn.discordapp.com/expired"}}}
 if err=contaboRefreshAttachments(source,msg);err!=nil {t.Fatal(err)}
 if msg.Content!="archived text" || msg.Attachments[0].URL!="https://cdn.discordapp.com/fresh" {t.Fatal("refresh changed archival content or retained expired URL")}
 msg.Attachments[0].Size=999
 if err=contaboRefreshAttachments(source,msg);err==nil {t.Fatal("mismatched attachment size accepted")}
}

func TestContaboArchiveRefreshRejectsMissingMessageAndChangedMedia(t *testing.T) {
 cases:=[]struct{name,body string}{
  {"deleted","[]"},
  {"neighbor",`[{"id":"99","channel_id":"123","attachments":[{"id":"456","size":12,"url":"https://cdn.discordapp.com/wrong"}]}]`},
  {"wrong channel",`[{"id":"100","channel_id":"other","attachments":[{"id":"456","size":12,"url":"https://cdn.discordapp.com/wrong"}]}]`},
  {"changed ID",`[{"id":"100","channel_id":"123","attachments":[{"id":"789","size":12,"url":"https://cdn.discordapp.com/wrong"}]}]`},
  {"changed size",`[{"id":"100","channel_id":"123","attachments":[{"id":"456","size":13,"url":"https://cdn.discordapp.com/wrong"}]}]`},
  {"missing URL",`[{"id":"100","channel_id":"123","attachments":[{"id":"456","size":12,"url":""}]}]`},
 }
 for _,tc:=range cases {t.Run(tc.name,func(t *testing.T){
  session,err:=discordgo.New("fixture-user-token");if err!=nil {t.Fatal(err)}
  session.Client=&http.Client{Transport:contaboTransport(func(r *http.Request)(*http.Response,error){
   return &http.Response{StatusCode:200,Header:make(http.Header),Body:io.NopCloser(strings.NewReader(tc.body))},nil
  })}
  msg:=&discordgo.Message{ID:"100",ChannelID:"123",Content:"archived text",Attachments:[]*discordgo.MessageAttachment{{ID:"456",Size:12,URL:"https://cdn.discordapp.com/original"}}}
  if err:=contaboRefreshAttachments(&User{Session:session},msg);err==nil {t.Fatal("missing or mismatched attachment accepted")}
  if msg.Content!="archived text" || msg.Attachments[0].URL!="https://cdn.discordapp.com/original" {t.Fatal("failed refresh changed source data")}
 })}
}

func TestContaboArchiveFailureStaysGatedAndDoesNotCrashOtherRooms(t *testing.T) {
 failed,other:=&Portal{},&Portal{}
 // The native converter can panic when Matrix/media sends fail. This is a
 // room failure, not permission to crash the process or enable live delivery.
 if failed.completeContaboArchive("123",func()error{panic(errors.New("media unavailable"))}) {t.Fatal("panic marked room ready")}
 if failed.contaboArchiveReady["123"] || !strings.Contains(failed.contaboArchiveErrors["123"],"media unavailable") {t.Fatal("failed room lost its blocker")}
 if !other.completeContaboArchive("456",func()error{return nil}) {t.Fatal("one failed room stopped another room")}
 if failed.completeContaboArchive("123",func()error{return errors.New("still unavailable")}) {t.Fatal("error marked room ready")}
 if !failed.completeContaboArchive("123",func()error{return nil}) {t.Fatal("repaired room could not resume")}
 if !failed.contaboArchiveReady["123"] || failed.contaboArchiveErrors["123"]!="" {t.Fatal("successful retry did not clear blocker")}
}

func TestContaboArchiveOrderingAndChannelIsolation(t *testing.T) {
 db,err:=sql.Open("sqlite3",":memory:"); if err!=nil {t.Fatal(err)}; defer db.Close()
 db.SetMaxOpenConns(1)
 _,err=db.Exec("CREATE TABLE messages(channel_id TEXT,id TEXT,json TEXT)"); if err!=nil {t.Fatal(err)}
 ids:=[]string{"100","9","9223372036854775808","10"}
 for _,id:=range ids {
  raw,_:=json.Marshal(map[string]interface{}{"id":id,"channel_id":"123","author":map[string]string{"id":"456"}})
  if _,err=db.Exec("INSERT INTO messages VALUES(?,?,?)","123",id,string(raw));err!=nil {t.Fatal(err)}
 }
 db.Exec("INSERT INTO messages VALUES('other','11','{}')")
 tx,err:=db.Begin(); if err!=nil {t.Fatal(err)}; defer tx.Rollback()
 rows,err:=contaboArchiveBatch(tx,"123",""); if err!=nil {t.Fatal(err)}
 want:=[]string{"9","10","100","9223372036854775808"}
 if len(rows)!=len(want) {t.Fatalf("wrong count: %d",len(rows))}
 for i,row:=range rows {if row.ID!=want[i] {t.Fatalf("wrong order at %d",i)}}
 rows,err=contaboArchiveBatch(tx,"123","100"); if err!=nil {t.Fatal(err)}
 if len(rows)!=1 || rows[0].ID!=want[3] {t.Fatal("resume cursor lost an unsigned snowflake")}
}

func TestContaboArchiveRejectsMismatchedSource(t *testing.T) {
 db,err:=sql.Open("sqlite3",":memory:"); if err!=nil {t.Fatal(err)}; defer db.Close()
 db.Exec("CREATE TABLE messages(channel_id TEXT,id TEXT,json TEXT)")
 db.Exec(`INSERT INTO messages VALUES('123','100','{"id":"100","channel_id":"other","author":{"id":"456"}}')`)
 tx,err:=db.Begin(); if err!=nil {t.Fatal(err)}; defer tx.Rollback()
 if _,err=contaboArchiveBatch(tx,"123","");err==nil {t.Fatal("invalid archive was accepted")}
}

func TestContaboArchiveSystemEventsArePreserved(t *testing.T) {
 original:=&discordgo.Message{ID:"100",ChannelID:"123",Type:discordgo.MessageTypeChannelPinnedMessage}
 converted:=contaboArchiveMessage(original)
 if converted.Type!=discordgo.MessageTypeDefault || converted.Content=="" {t.Fatal("system event would be dropped")}
 if original.Type!=discordgo.MessageTypeChannelPinnedMessage || original.Content!="" {t.Fatal("archived source was mutated")}
}
