package email

import (
 "context"
 "database/sql"
 "path/filepath"
 "strings"
 "testing"
 "time"

 _ "github.com/mattn/go-sqlite3"
 "github.com/rs/zerolog"
 "maunium.net/go/mautrix/bridgev2"
 "maunium.net/go/mautrix/bridgev2/database"
 "maunium.net/go/mautrix/bridgev2/networkid"
 "maunium.net/go/mautrix/event"
)

func TestContaboContactPersistenceAndAccountIsolation(t *testing.T){
 ctx:=context.Background();path:=filepath.Join(t.TempDir(),"bridge.db")
 db,err:=sql.Open("sqlite3",path);if err!=nil{t.Fatal(err)}
 store,err:=NewContactStore(ctx,db,"mail");if err!=nil{t.Fatal(err)}
 older:=time.Unix(100,0);newer:=time.Unix(200,0)
 first:=&EmailThread{ThreadID:"a",Subject:"A",LastFrom:"alice@example.com",LastTo:[]string{"me@gmail.com"},MessageID:"a"}
 a,err:=store.Record(ctx,"me",first,"a","alice@example.com",older);if err!=nil{t.Fatal(err)}
 second:=&EmailThread{ThreadID:"b",Subject:"B",LastFrom:"alice@example.com",MessageID:"b"}
 b,err:=store.Record(ctx,"me",second,"b","alice@example.com",newer);if err!=nil{t.Fatal(err)}
 if ContactPortalID(a.Contact)!=ContactPortalID(b.Contact)||a.RootID==b.RootID{t.Fatal("subjects must share a contact room but retain distinct roots")}
 reply:=&EmailThread{ThreadID:"a",Subject:"A",LastFrom:"bob@example.com",LastTo:[]string{"me@gmail.com"},MessageID:"reply"}
 r,err:=store.Record(ctx,"me",reply,"reply","bob@example.com",newer);if err!=nil{t.Fatal(err)}
 if r.Contact!=a.Contact||r.RootID!=a.RootID{t.Fatal("recipient changes moved an existing email chain")}
 if _,err=store.Record(ctx,"me",first,"old","alice@example.com",older);err!=nil{t.Fatal(err)}
 if err=db.Close();err!=nil{t.Fatal(err)}
 db,err=sql.Open("sqlite3",path);if err!=nil{t.Fatal(err)};defer db.Close()
 store,err=NewContactStore(ctx,db,"mail");if err!=nil{t.Fatal(err)}
 restored,err:=store.GetChain(ctx,"me","a");if err!=nil||restored.Thread.LastFrom!="bob@example.com"{t.Fatalf("restart/older backfill lost latest reply context: %#v %v",restored,err)}
 snapshot,err:=store.GetMessage(ctx,"me","contact-email:a");if err!=nil||snapshot.Thread.LastFrom!="alice@example.com"{t.Fatal("explicit replies must retain the selected message's recipients")}
 other,err:=store.GetMessage(ctx,"friend","a");if err!=nil||other!=nil{t.Fatal("cross-account context leak")}
 otherStore,_:=NewContactStore(ctx,db,"another-bridge");other,err=otherStore.GetMessage(ctx,"me","a");if err!=nil||other!=nil{t.Fatal("cross-bridge context leak")}
}

func TestContaboContactAddressSelection(t *testing.T){
 cases:=[]struct{p ParsedEmail;want string}{
  {ParsedEmail{From:"Alice <ALICE@example.com>",To:[]string{"me@gmail.com"}},"alice@example.com"},
  {ParsedEmail{From:"me@gmail.com",To:[]string{"ME@gmail.com","b@example.com","a@example.com"}},"a@example.com,b@example.com"},
  {ParsedEmail{From:"me+alias@gmail.com",To:[]string{"a@example.com"}},"a@example.com"},
 }
 for _,tc:=range cases{got,err:=ContactForEmail(&tc.p,[]string{"me@gmail.com","me+alias@gmail.com"});if err!=nil||got!=tc.want{t.Fatalf("got %q %v want %q",got,err,tc.want)}}
 if contact,err:=ContactForEmail(&ParsedEmail{From:"me@gmail.com",To:[]string{"me@gmail.com"}},[]string{"me@gmail.com"});err!=nil||contact!="me@gmail.com"{t.Fatal("self-only mail must have its own room rather than pausing the import")}
}

func TestContaboContactProcessorAndThreadRelations(t *testing.T){
 ctx:=context.Background();db,_:=sql.Open("sqlite3",filepath.Join(t.TempDir(),"mail.db"));defer db.Close()
 store,err:=NewContactStore(ctx,db,"mail");if err!=nil{t.Fatal(err)}
 logger:=zerolog.Nop();processor:=NewProcessor(&logger,NewThreadManager(nil),true,"test");processor.Contacts=store
 login:=&bridgev2.UserLogin{UserLogin:&database.UserLogin{ID:networkid.UserLoginID("email:me@gmail.com")}}
 p:=&ParsedEmail{MessageID:"first",Subject:"First subject",From:"alice@example.com",To:[]string{"me@gmail.com"},Date:time.Unix(100,0)}
 message,err:=processor.ProcessParsedEmail(ctx,p,login,"INBOX");if err!=nil{t.Fatal(err)}
 p2:=&ParsedEmail{MessageID:"second",Subject:"Second subject",From:"alice@example.com",To:[]string{"me@gmail.com"},Date:time.Unix(101,0)}
 second,err:=processor.ProcessParsedEmail(ctx,p2,login,"INBOX");if err!=nil{t.Fatal(err)}
 if message.PortalKey!=second.PortalKey||message.ContactRoot==second.ContactRoot{t.Fatal("incorrect contact grouping")}
 converted:=&bridgev2.ConvertedMessage{Parts:[]*bridgev2.ConvertedMessagePart{{Content:&event.MessageEventContent{MsgType:event.MsgText,Body:"Email body"}}}}
 evt:=&EmailMatrixEvent{emailMessage:message};evt.applyContactRelations(converted)
 if converted.ThreadRoot==nil||*converted.ThreadRoot!=message.MessageID||!strings.Contains(converted.Parts[0].Content.Body,"First subject"){t.Fatal("missing native Matrix thread root/subject")}
}

func TestContaboThreadCacheScopesIdenticalMessageIDs(t *testing.T){
 tm:=NewThreadManager(nil)
 tm.CacheForReceiver("first",&EmailThread{ThreadID:"root",MessageID:"same",Subject:"private first"})
 tm.CacheForReceiver("second",&EmailThread{ThreadID:"root",MessageID:"same",Subject:"private second"})
 first:=tm.DetermineThread("first",&ParsedEmail{MessageID:"reply",InReplyTo:"same",From:"a@example.com"})
 if first.Subject!="private first"{t.Fatal("in-memory reply lookup crossed account boundary")}
}
