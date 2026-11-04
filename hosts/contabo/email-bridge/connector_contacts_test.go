package connector

import (
 "context"
 "database/sql"
 "net/mail"
 "path/filepath"
 "strings"
 "testing"
 "time"

 "github.com/Leicas/matrimail/pkg/email"
 "github.com/rs/zerolog"
 _ "github.com/mattn/go-sqlite3"
 "maunium.net/go/mautrix"
 "maunium.net/go/mautrix/bridgev2"
 "maunium.net/go/mautrix/bridgev2/database"
 "maunium.net/go/mautrix/bridgev2/networkid"
 "maunium.net/go/mautrix/event"
 "maunium.net/go/mautrix/id"
)

type contactCaptureSender struct{messages []string;targets [][]string}
func(s *contactCaptureSender)Send(_ context.Context,raw []byte,_ string,to []string,_ string)(string,error){s.messages=append(s.messages,string(raw));s.targets=append(s.targets,to);return "sent-"+time.Now().Format("150405.000000000"),nil}
func(s *contactCaptureSender)Provider()string{return "test"}
func(s *contactCaptureSender)Close()error{return nil}

func TestContaboContactRepliesUseSelectedChainAfterRestart(t *testing.T){
 ctx:=context.Background();db,err:=sql.Open("sqlite3",filepath.Join(t.TempDir(),"mail.db"));if err!=nil{t.Fatal(err)};defer db.Close()
 store,err:=email.NewContactStore(ctx,db,"mail");if err!=nil{t.Fatal(err)}
 receiver:=networkid.UserLoginID("email:me@gmail.com")
 for _,chain:=range []struct{id,subject,sender string}{{"first","First subject","alice@example.com"},{"second","Second subject","alice@example.com"}}{
  _,err=store.Record(ctx,string(receiver),&email.EmailThread{ThreadID:chain.id,Subject:chain.subject,MessageID:chain.id,LastFrom:chain.sender,LastTo:[]string{"me@gmail.com"},Participants:[]string{"me@gmail.com",chain.sender}},chain.id,chain.sender,time.Now());if err!=nil{t.Fatal(err)}
 }
 // A fresh connector with no ThreadManager cache simulates a service restart.
 logger:=zerolog.Nop();login:=&bridgev2.UserLogin{UserLogin:&database.UserLogin{ID:receiver,UserMXID:id.UserID("@me:example.com")},Log:logger}
 sender:=&contactCaptureSender{}
 client:=&EmailClient{Main:&EmailConnector{Contacts:store},UserLogin:login,Email:"me@gmail.com",Sender:sender}
 key:=networkid.PortalKey{ID:email.ContactPortalID("alice@example.com"),Receiver:receiver}
 portal:=&bridgev2.Portal{Portal:&database.Portal{PortalKey:key}}
 msg:=&bridgev2.MatrixMessage{MatrixEventBase:bridgev2.MatrixEventBase[*event.MessageEventContent]{Portal:portal,Content:&event.MessageEventContent{MsgType:event.MsgText,Body:"Reply to the first subject"}},ThreadRoot:&database.Message{ID:email.ContactMessageID("first"),Room:key}}
 response,err:=client.handleMatrixMessageOutbound(ctx,msg);if err!=nil{t.Fatal(err)}
 if response.DB.ThreadRoot!=email.ContactMessageID("first"){t.Fatal("outbound Matrix thread root lost")}
 parsed,err:=mail.ReadMessage(strings.NewReader(sender.messages[0]));if err!=nil{t.Fatal(err)}
 if parsed.Header.Get("Subject")!="Re: First subject"||parsed.Header.Get("In-Reply-To")!="<first>"{t.Fatalf("wrong email chain: %v",parsed.Header)}
 if len(sender.targets[0])!=1||sender.targets[0][0]!="alice@example.com"{t.Fatalf("wrong recipients: %v",sender.targets)}
 // Explicit replies preserve the selected email, even when another thread is newer.
 msg.ThreadRoot=nil;msg.ReplyTo=&database.Message{ID:email.ContactMessageID("second"),Room:key}
 if _,err=client.handleMatrixMessageOutbound(ctx,msg);err!=nil{t.Fatal(err)}
 parsed,_=mail.ReadMessage(strings.NewReader(sender.messages[1]));if parsed.Header.Get("Subject")!="Re: Second subject"{t.Fatal("explicit reply selected the wrong subject")}
 // A top-level send is a new email, not a reply to the most recent chain.
 msg.ReplyTo=nil;msg.Content.Body="A new subject\nNew body"
 if _,err=client.handleMatrixMessageOutbound(ctx,msg);err!=nil{t.Fatal(err)}
 parsed,_=mail.ReadMessage(strings.NewReader(sender.messages[2]));if parsed.Header.Get("In-Reply-To")!=""||parsed.Header.Get("Subject")!="A new subject"{t.Fatal("top-level send leaked an unrelated email's headers")}
 // An unresolved or cross-account target must fail before invoking SMTP.
 msg.Content.RelatesTo=&event.RelatesTo{Type:event.RelThread,EventID:"$missing"}
 if _,err=client.handleMatrixMessageOutbound(ctx,msg);err==nil||len(sender.messages)!=3{t.Fatal("unmapped reply was sent")}
 msg.Content.RelatesTo=nil;msg.ThreadRoot=&database.Message{ID:email.ContactMessageID("first"),Room:networkid.PortalKey{ID:key.ID,Receiver:"friend"}}
 if _,err=client.handleMatrixMessageOutbound(ctx,msg);err==nil||len(sender.messages)!=3{t.Fatal("cross-account reply was sent")}
}

func TestContaboContactRoomPermissionsAndOwnership(t *testing.T){
 ec:=&EmailConnector{}
 info,err:=ec.contactChatInfo(email.ContactPortalID("alice@example.com"));if err!=nil{t.Fatal(err)}
 levels:=info.Members.PowerLevels
 if levels.Events[event.EventMessage]!=0||levels.Events[event.EventEncrypted]!=0{t.Fatal("email replies remain read-only")}
 if *levels.StateDefault<=0||*levels.Invite<=0{t.Fatal("sending replies must not grant room administration")}
 login:=&bridgev2.UserLogin{UserLogin:&database.UserLogin{ID:"email:me@gmail.com"}}
 portal:=&bridgev2.Portal{Portal:&database.Portal{PortalKey:networkid.PortalKey{ID:email.ContactPortalID("alice@example.com"),Receiver:login.ID},MXID:"!room:example.com"}}
 if !contactRoomOwnedBy(portal,login){t.Fatal("owned Matrimail room not recognized")}
 portal.Receiver="friend";if contactRoomOwnedBy(portal,login){t.Fatal("cross-account autojoin")}
 portal.Receiver=login.ID;portal.ID="unrelated-room";if contactRoomOwnedBy(portal,login){t.Fatal("arbitrary invite accepted")}
}

func TestContaboGroupReplyUsesLatestEmailNotEntireHistoricalParticipantSet(t *testing.T){
 group:=&email.EmailThread{
  Participants:[]string{"me@gmail.com","alice@example.com","bob@example.com"},
  LastFrom:"alice@example.com",
  LastTo:[]string{"me@gmail.com"},
  LastCc:[]string{},
 }
 to,cc,err:=resolveReplyAllRecipients(group,[]string{"me@gmail.com"})
 if err!=nil{t.Fatal(err)}
 if len(to)!=1||to[0].Address!="alice@example.com"||len(cc)!=0{
  t.Fatalf("reply-all should honor newest message's recipients, not historical group: to=%v cc=%v",to,cc)
 }
 group.LastCc=[]string{"bob@example.com"}
 to,cc,err=resolveReplyAllRecipients(group,[]string{"me@gmail.com"})
 if err!=nil||len(to)!=1||len(cc)!=1||cc[0].Address!="bob@example.com"{
  t.Fatalf("reply-all must restore Bob only when he is CC'd on selected mail: to=%v cc=%v err=%v",to,cc,err)
 }
}

func TestContaboGroupRoomMetadata(t *testing.T){
 ec:=&EmailConnector{}
 group:=email.ContactPortalID("alice@example.com,bob@example.com")
 info,err:=ec.contactChatInfo(group);if err!=nil{t.Fatal(err)}
 if info.Name==nil||!strings.Contains(*info.Name,"Group email"){
  t.Fatalf("multi-party group room not identified: %+v",info.Name)
 }
 if info.Topic==nil||!strings.Contains(*info.Topic,"selected email"){
  t.Fatalf("group room topic should explain explicit per-message replies: %+v",info.Topic)
 }
 if len(info.Members.MemberMap)!=3{t.Fatalf("unexpected group member count %d",len(info.Members.MemberMap))}
 direct,err:=ec.contactChatInfo(email.ContactPortalID("alice@example.com"))
 if err!=nil{t.Fatal(err)}
 if direct.Name==nil||*direct.Name!="alice@example.com"{t.Fatalf("direct room mislabeled: %v",direct.Name)}
}

func TestContaboComposeCcAndDraftReplyHeaders(t *testing.T){
 thread:=&email.EmailThread{ThreadID:"compose-fixture",MessageID:"actual-email@example.com",Participants:[]string{"me@gmail.com","alice@example.com","copy@example.com"},Cc:[]string{"copy@example.com"}}
 to,cc,err:=resolveComposeRecipients(thread,[]string{"me@gmail.com"});if err!=nil{t.Fatal(err)}
 if len(to)!=1||to[0].Address!="alice@example.com"||len(cc)!=1||cc[0].Address!="copy@example.com"{t.Fatal("compose lost To/Cc separation")}
 parent,refs:=computeReplyChain(thread,&database.Message{ID:email.ContactMessageID("compose-fixture")})
 if parent!="actual-email@example.com"||len(refs)!=1||refs[0]!=parent{t.Fatal("draft notice identifier leaked into email reply headers")}
 ec:=&EmailConnector{}
 first:=&bridgev2.Portal{Portal:&database.Portal{PortalKey:networkid.PortalKey{ID:"contact:same",Receiver:"first"}}}
 second:=&bridgev2.Portal{Portal:&database.Portal{PortalKey:networkid.PortalKey{ID:first.ID,Receiver:"second"}}}
 ec.MarkPortalNextReplyDM(portalReplyModeKey(first))
 if ec.consumePortalNextReplyDM(portalReplyModeKey(second)){t.Fatal("reply-only toggle crossed accounts")}
 if !ec.consumePortalNextReplyDM(portalReplyModeKey(first)){t.Fatal("reply-only toggle was lost")}
}

type contactMatrixFixture struct{
 bridgev2.MatrixConnector
 levels *event.PowerLevelsEventContent
 membership event.Membership
 intent *contactIntentFixture
}
func(m *contactMatrixFixture)GetPowerLevels(context.Context,id.RoomID)(*event.PowerLevelsEventContent,error){return m.levels,nil}
func(m *contactMatrixFixture)GetMemberInfo(context.Context,id.RoomID,id.UserID)(*event.MemberEventContent,error){return &event.MemberEventContent{Membership:m.membership},nil}
func(m *contactMatrixFixture)NewUserIntent(context.Context,id.UserID,string)(bridgev2.MatrixAPI,string,error){return m.intent,"saved",nil}
type contactIntentFixture struct{bridgev2.MatrixAPI;joins,states int}
func(i *contactIntentFixture)EnsureJoined(context.Context,id.RoomID,...bridgev2.EnsureJoinedParams)error{i.joins++;return nil}
func(i *contactIntentFixture)SendState(context.Context,id.RoomID,event.Type,string,*event.Content,time.Time)(*mautrix.RespSendEvent,error){i.states++;return &mautrix.RespSendEvent{},nil}

func TestContaboRepairUnblocksEncryptedRepliesAndAcceptsOnlyPortalInvites(t *testing.T){
 ctx:=context.Background();intent:=&contactIntentFixture{}
 mx:=&contactMatrixFixture{levels:&event.PowerLevelsEventContent{Events:map[string]int{event.EventMessage.Type:101,event.EventEncrypted.Type:101}},membership:event.MembershipInvite,intent:intent}
 bridge:=&bridgev2.Bridge{Matrix:mx,Bot:intent}
 user:=&bridgev2.User{User:&database.User{MXID:"@me:example.com",AccessToken:"saved"},Bridge:bridge,Log:zerolog.Nop()}
 login:=&bridgev2.UserLogin{UserLogin:&database.UserLogin{ID:"email:me@gmail.com",UserMXID:user.MXID},User:user}
 ec:=&EmailConnector{Bridge:bridge,Config:Config{AutoJoinRooms:true}}
 portal:=&bridgev2.Portal{Portal:&database.Portal{PortalKey:networkid.PortalKey{ID:email.ContactPortalID("legacy@example.com"),Receiver:login.ID},MXID:"!room:example.com"}}
 if err:=ec.repairContactRoom(ctx,portal,login);err!=nil{t.Fatal(err)}
 if intent.joins!=1||intent.states!=1||mx.levels.Events[event.EventMessage.Type]!=0||mx.levels.Events[event.EventEncrypted.Type]!=0{t.Fatal("repair did not unblock posting and accept invitation")}
 mx.membership=event.MembershipLeave
 if err:=ec.repairContactRoom(ctx,portal,login);err!=nil||intent.joins!=1{t.Fatal("explicitly left room was force-joined")}
 portal.ID="thread:retired";mx.membership=event.MembershipInvite
 if err:=ec.repairContactRoom(ctx,portal,login);err==nil||intent.joins!=1{t.Fatal("obsolete room incorrectly repaired")}
}
