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

func TestContaboSameEmailFromMultipleFoldersKeepsOneRoom(t *testing.T){
 ctx:=context.Background()
 db,err:=sql.Open("sqlite3",filepath.Join(t.TempDir(),"two-folders.db"));if err!=nil{t.Fatal(err)}
 defer db.Close()
 store,err:=NewContactStore(ctx,db,"mail");if err!=nil{t.Fatal(err)}
 original:=&EmailThread{ThreadID:"inbox-root",Subject:"Project",LastFrom:"alice@example.com"}
 first,err:=store.Record(ctx,"email:me@gmail.com",original,"shared-rfc-message-id",
  "alice@example.com",time.Unix(100,0))
 if err!=nil{t.Fatal(err)}
 // All Mail (or a restarted thread cache) observes the same RFC Message-ID
 // with a different inferred chain and broader From/To/Cc participant set.
 reinterpreted:=&EmailThread{ThreadID:"all-mail-root",Subject:"Re: Project",LastFrom:"bob@example.com"}
 second,err:=store.Record(ctx,"email:me@gmail.com",reinterpreted,"shared-rfc-message-id",
  "alice@example.com,bob@example.com",time.Unix(200,0))
 if err!=nil{t.Fatal(err)}
 if second.Contact!=first.Contact||second.RootID!=first.RootID||second.Thread.ThreadID!=original.ThreadID{
  t.Fatalf("same source email migrated between v3 rooms: %#v %#v",first,second)
 }
 // A duplicate source email must not have created a second chain root.
 row:=db.QueryRowContext(ctx,"SELECT COUNT(*) FROM contabo_email_chain_v3 WHERE receiver=?",
  "email:me@gmail.com")
 var chains int
 if err=row.Scan(&chains);err!=nil||chains!=1{t.Fatalf("duplicate email created %d chains: %v",chains,err)}
 // The same RFC Message-ID in another authenticated account is independent.
 other,err:=store.Record(ctx,"email:friend@gmail.com",reinterpreted,"shared-rfc-message-id",
  "alice@example.com,bob@example.com",time.Unix(300,0))
 if err!=nil||other.Contact!="alice@example.com,bob@example.com"{
  t.Fatalf("cross-account message routing leaked: %#v %v",other,err)
 }
}

func TestContaboContactAddressSelection(t *testing.T){
 cases:=[]struct{p ParsedEmail;want string}{
  {ParsedEmail{From:"Alice <ALICE@example.com>",To:[]string{"me@gmail.com"}},"alice@example.com"},
  {ParsedEmail{From:"Alice <ALICE@example.com>",To:[]string{"me@gmail.com","bob@example.com"}},"alice@example.com,bob@example.com"},
  {ParsedEmail{From:"Bob <BOB@example.com>",To:[]string{"alice@example.com","me@gmail.com"}},"alice@example.com,bob@example.com"},
  {ParsedEmail{From:"me@gmail.com",To:[]string{"alice@example.com"},Cc:[]string{"BOB@example.com"}},"alice@example.com,bob@example.com"},
  {ParsedEmail{From:"Alice <ALICE@example.com>",To:[]string{"me+alias@gmail.com"},Cc:[]string{"Bob <BOB@example.com>","alice@example.com"}},"alice@example.com,bob@example.com"},
  {ParsedEmail{From:"me@gmail.com",To:[]string{"ME@gmail.com","b@example.com","a@example.com"}},"a@example.com,b@example.com"},
  {ParsedEmail{From:"me+alias@gmail.com",To:[]string{"a@example.com"}},"a@example.com"},
  {ParsedEmail{From:"a@example.com",To:[]string{"me+tracking@gmail.com"}},
    "a@example.com"},
  {ParsedEmail{From:"b@example.com",To:[]string{"m.e@gmail.com"},Cc:[]string{"a@example.com"}},
    "a@example.com,b@example.com"},
  {ParsedEmail{From:"a@example.com",To:[]string{"me@googlemail.com","bob@example.com"}},
    "a@example.com,bob@example.com"},
 }
 for _,tc:=range cases{got,err:=ContactForEmail(&tc.p,[]string{"me@gmail.com","me+alias@gmail.com"});if err!=nil||got!=tc.want{t.Fatalf("got %q %v want %q",got,err,tc.want)}}
 if contact,err:=ContactForEmail(&ParsedEmail{From:"me@gmail.com",To:[]string{"me@gmail.com"}},[]string{"me@gmail.com"});err!=nil||contact!="me@gmail.com"{t.Fatal("self-only mail must have its own room rather than pausing the import")}
 // Regression from Nov 4: a historical message without parseable From/To/Cc
 // used to halt the entire INBOX import. Preserve it in the self room.
 for _,p:=range []*ParsedEmail{
  {MessageID:"no-usable-address",From:"mailer-daemon",Subject:"System-generated"},
  {MessageID:"bad-from",From:"not-an-address",To:[]string{"unparseable"}},
  {MessageID:"bcc-only",From:"automated-system",Bcc:[]string{"other@example.com"}},
 }{
  got,err:=ContactForEmail(p,[]string{"me@gmail.com","me+alias@gmail.com"})
  if err!=nil||got!="me@gmail.com"{t.Fatalf("addressless mail must use owner-scoped self room, got %q: %v",got,err)}
 }
 if _,err:=ContactForEmail(&ParsedEmail{MessageID:"invalid"},nil);err==nil{
  t.Fatal("missing login email must not silently create an unowned room")
 }
}

func TestContaboGroupConversationStaysInOneRoomAcrossReplyAll(t *testing.T){
 ctx:=context.Background()
 db,err:=sql.Open("sqlite3",filepath.Join(t.TempDir(),"group.db"));if err!=nil{t.Fatal(err)}
 defer db.Close()
 store,err:=NewContactStore(ctx,db,"mail");if err!=nil{t.Fatal(err)}
 logger:=zerolog.Nop()
 proc:=NewProcessor(&logger,NewThreadManager(nil),true,"test");proc.Contacts=store
 login:=&bridgev2.UserLogin{UserLogin:&database.UserLogin{ID:networkid.UserLoginID("email:me@gmail.com")}}
 inputs:=[]*ParsedEmail{
  {MessageID:"root",Subject:"Group discussion",From:"alice@example.com",To:[]string{"me@gmail.com"},Cc:[]string{"bob@example.com"},Date:time.Unix(100,0)},
  {MessageID:"reply-bob",Subject:"Re: Group discussion",InReplyTo:"root",References:[]string{"root"},From:"bob@example.com",To:[]string{"alice@example.com","me@gmail.com"},Date:time.Unix(101,0)},
  {MessageID:"reply-me",Subject:"Re: Group discussion",InReplyTo:"reply-bob",References:[]string{"root","reply-bob"},From:"me@gmail.com",To:[]string{"bob@example.com","alice@example.com"},Date:time.Unix(102,0)},
  // A direct reply late in the chain must not create a separate room.
  {MessageID:"reply-direct",Subject:"Re: Group discussion",InReplyTo:"reply-me",References:[]string{"root","reply-bob","reply-me"},From:"alice@example.com",To:[]string{"me@gmail.com"},Date:time.Unix(103,0)},
 }
 var first networkid.PortalKey
 var root networkid.MessageID
 for i,p:=range inputs{
  message,err:=proc.ProcessParsedEmail(ctx,p,login,"INBOX");if err!=nil{t.Fatal(err)}
  if i==0{first=message.PortalKey;root=message.ContactRoot}
  if message.PortalKey!=first||message.ContactRoot!=root{
   t.Fatalf("group chain fragmented on message %d: %#v vs %#v",i,message.PortalKey,first)
  }
 }
 if want:=ContactPortalID("alice@example.com,bob@example.com");first.ID!=want{
  t.Fatalf("expected group contact room %q, got %q",want,first.ID)
 }
 if _,err:=store.GetMessage(ctx,"different-account","root");err!=nil{t.Fatal(err)}
 // Other subjects for Alice alone remain in her direct room.
 direct:=&ParsedEmail{MessageID:"independent",Subject:"Direct",From:"alice@example.com",To:[]string{"me@gmail.com"},Date:time.Unix(104,0)}
 message,err:=proc.ProcessParsedEmail(ctx,direct,login,"INBOX")
 if err!=nil||message.PortalKey.ID!=ContactPortalID("alice@example.com"){t.Fatalf("independent direct conversation incorrectly merged: %#v %v",message,err)}
}

// A restarted IMAP replay can see the same RFC conversation with a different
// inferred thread ID or narrower To/Cc list. Persisted ancestry must win.
func TestContaboPersistentReplyAncestryPreventsGroupFragmentation(t *testing.T){
 ctx:=context.Background()
 db,err:=sql.Open("sqlite3",filepath.Join(t.TempDir(),"group-replies.db"));if err!=nil{t.Fatal(err)}
 defer db.Close()
 store,err:=NewContactStore(ctx,db,"mail");if err!=nil{t.Fatal(err)}
 log:=zerolog.Nop()
 login:=&bridgev2.UserLogin{UserLogin:&database.UserLogin{ID:networkid.UserLoginID("email:me@gmail.com")}}
 proc:=NewProcessor(&log,NewThreadManager(nil),true,"test")
 proc.Contacts=store
 first,err:=proc.ProcessParsedEmail(ctx,&ParsedEmail{
  MessageID:"root",From:"alice@example.com",
  To:[]string{"me@gmail.com","bob@example.com"},
  Subject:"Three-person research",Date:time.Unix(100,0),
 },login,"INBOX")
 if err!=nil{t.Fatal(err)}
 // Simulate cache loss and a reply-only-to-sender that does not mention Bob.
 proc2:=NewProcessor(&log,NewThreadManager(nil),true,"test")
 proc2.Contacts=store
 second,err:=proc2.ProcessParsedEmail(ctx,&ParsedEmail{
  MessageID:"reply-narrow",InReplyTo:"root",References:[]string{"root"},
  From:"alice@example.com",To:[]string{"me+archive@gmail.com"},
  Subject:"Re: Three-person research",Date:time.Unix(101,0),
 },login,"[Gmail]/All Mail")
 if err!=nil{t.Fatal(err)}
 if second.PortalKey!=first.PortalKey||second.ContactRoot!=first.ContactRoot{
  t.Fatalf("lost group room across cache eviction or CC removal: %#v vs %#v",first.PortalKey,second.PortalKey)
 }
 // A third reply with a missing immediate parent can still follow References.
 proc3:=NewProcessor(&log,NewThreadManager(nil),true,"test")
 proc3.Contacts=store
 third,err:=proc3.ProcessParsedEmail(ctx,&ParsedEmail{
  MessageID:"reply-grandparent",InReplyTo:"missing-parent",
  References:[]string{"root","missing-parent"},
  From:"bob@example.com",To:[]string{"me@gmail.com"},
  Subject:"Re: Three-person research",Date:time.Unix(102,0),
 },login,"[Gmail]/All Mail")
 if err!=nil{t.Fatal(err)}
 if third.PortalKey!=first.PortalKey||third.ContactRoot!=first.ContactRoot{
  t.Fatalf("grandparent reference failed to preserve group room: %#v",third.PortalKey)
 }
 // Identical subject and one overlapping participant do not justify merging.
 independent,err:=proc3.ProcessParsedEmail(ctx,&ParsedEmail{
  MessageID:"independent",From:"alice@example.com",To:[]string{"me@gmail.com"},
  Subject:"Three-person research",Date:time.Unix(103,0),
 },login,"INBOX")
 if err!=nil{t.Fatal(err)}
 if independent.PortalKey.ID!=ContactPortalID("alice@example.com"){
  t.Fatal("unrelated direct mail was absorbed into a group")
 }
 another,err:=proc3.ProcessParsedEmail(ctx,&ParsedEmail{
  MessageID:"independent-group",From:"alice@example.com",
  To:[]string{"me@gmail.com","carol@example.com"},
  Subject:"Three-person research",Date:time.Unix(104,0),
 },login,"INBOX")
 if err!=nil{t.Fatal(err)}
 if another.PortalKey.ID!=ContactPortalID("alice@example.com,carol@example.com"){
  t.Fatal("unrelated group was merged based on subject/contact overlap")
 }
}

func TestContaboAddresslessHistoryKeepsAnExistingChain(t *testing.T){
 ctx:=context.Background()
 db,err:=sql.Open("sqlite3",filepath.Join(t.TempDir(),"addressless.db"));if err!=nil{t.Fatal(err)}
 defer db.Close()
 store,err:=NewContactStore(ctx,db,"mail");if err!=nil{t.Fatal(err)}
 logger:=zerolog.Nop()
 processor:=NewProcessor(&logger,NewThreadManager(nil),true,"test")
 processor.Contacts=store
 login:=&bridgev2.UserLogin{UserLogin:&database.UserLogin{ID:networkid.UserLoginID("email:me@gmail.com")}}
 root:=&ParsedEmail{MessageID:"root",Subject:"Conversation",From:"alice@example.com",To:[]string{"me@gmail.com"},Date:time.Unix(100,0)}
 first,err:=processor.ProcessParsedEmail(ctx,root,login,"INBOX");if err!=nil{t.Fatal(err)}
 reply:=&ParsedEmail{MessageID:"reply",InReplyTo:"root",References:[]string{"root"},From:"malformed-sender",Subject:"Re: Conversation",Date:time.Unix(101,0)}
 second,err:=processor.ProcessParsedEmail(ctx,reply,login,"INBOX");if err!=nil{t.Fatal(err)}
 if second.PortalKey!=first.PortalKey||second.ContactRoot!=first.ContactRoot{
  t.Fatal("missing headers split a reply away from its established contact chain")
 }
 independent:=&ParsedEmail{MessageID:"standalone",From:"mailer-daemon",Subject:"Automatic system message",Date:time.Unix(102,0)}
 third,err:=processor.ProcessParsedEmail(ctx,independent,login,"INBOX");if err!=nil{t.Fatal(err)}
 if third.PortalKey.ID!=ContactPortalID("me@gmail.com"){
  t.Fatalf("addressless source email must appear in account self room, got %q",third.PortalKey.ID)
 }
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
