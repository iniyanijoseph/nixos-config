package connector

import (
 "context"
 "fmt"
 netmail "net/mail"
 "strings"
 "time"

 "github.com/google/uuid"
 "github.com/Leicas/matrimail/pkg/email"
 matrixrooms "github.com/Leicas/matrimail/pkg/matrix"
 "go.mau.fi/util/ptr"
 "maunium.net/go/mautrix/bridgev2"
 "maunium.net/go/mautrix/bridgev2/commands"
 "maunium.net/go/mautrix/bridgev2/database"
 "maunium.net/go/mautrix/bridgev2/networkid"
 "maunium.net/go/mautrix/event"
 "maunium.net/go/mautrix/id"
)

func(ec *EmailConnector)contactChatInfo(portalID networkid.PortalID)(*bridgev2.ChatInfo,error){
 contact,err:=email.ContactFromPortal(portalID);if err!=nil{return nil,err}
 members:=map[networkid.UserID]bridgev2.ChatMember{
  "":{EventSender:bridgev2.EventSender{IsFromMe:true},Membership:event.MembershipJoin,PowerLevel:ptr.Ptr(0)},
 }
 for _,address:=range strings.Split(contact,","){
  ghost:=MakeUserID(address)
  members[ghost]=bridgev2.ChatMember{EventSender:bridgev2.EventSender{Sender:ghost},Membership:event.MembershipJoin,PowerLevel:ptr.Ptr(0)}
 }
 return &bridgev2.ChatInfo{
  Name:ptr.Ptr(contact),Topic:ptr.Ptr("Email contact — each subject is a Matrix thread. Reply inside its thread; a message outside a thread starts a new email."),
  Type:ptr.Ptr(database.RoomTypeDefault),
  Members:&bridgev2.ChatMemberList{MemberMap:members,IsFull:false,PowerLevels:matrixrooms.BuildEmailPowerLevels()},
 },nil
}

// Select context by the explicit reply first, otherwise by the Matrix thread.
// Never silently use the most recent unrelated email in a contact room.
func(ec *EmailClient)contactOutboundThread(ctx context.Context,msg *bridgev2.MatrixMessage)(*email.EmailThread,error){
 contact,err:=email.ContactFromPortal(msg.Portal.ID);if err!=nil{return nil,err}
 receiver:=string(ec.UserLogin.ID)
 target:=msg.ReplyTo
 if target==nil{target=msg.ThreadRoot}
 if target!=nil{
  if target.Room!=msg.Portal.PortalKey{return nil,fmt.Errorf("reply target belongs to another email room/account")}
  chain,err:=ec.Main.Contacts.GetMessage(ctx,receiver,string(target.ID));if err!=nil{return nil,err}
  if chain==nil||chain.Thread==nil||chain.Contact!=contact{return nil,fmt.Errorf("email reply context unavailable; choose a bridged email thread")}
  if msg.ReplyTo==nil||chain.Thread.IsDraft{
   chain,err=ec.Main.Contacts.GetChain(ctx,receiver,chain.Thread.ThreadID);if err!=nil{return nil,err}
  }
  if chain==nil||chain.Thread==nil{return nil,fmt.Errorf("email chain unavailable")}
  return chain.Thread,nil
 }
 if msg.Content.RelatesTo!=nil&&(msg.Content.RelatesTo.GetThreadParent()!=""||msg.Content.RelatesTo.GetReplyTo()!=""){
  return nil,fmt.Errorf("unmapped email reply target; no email was sent")
 }
 return &email.EmailThread{ThreadID:"compose-"+uuid.NewString(),Subject:deriveSubjectFromBody(msg.Content.Body),
  Participants:append(strings.Split(contact,","),ec.Email),IsDraft:true},nil
}

func portalReplyModeKey(portal *bridgev2.Portal)networkid.PortalID{
 if portal.Receiver==""{return portal.ID}
 return networkid.PortalID(string(portal.Receiver)+"\x00"+string(portal.ID))
}

func resolveComposeRecipients(thread *email.EmailThread,selves []string)([]netmail.Address,[]netmail.Address,error){
 own:=selvesSet(selves);seen:=map[string]bool{};ccSet:=map[string]bool{}
 for _,value:=range thread.Cc{if addr,err:=netmail.ParseAddress(value);err==nil{ccSet[strings.ToLower(addr.Address)]=true}}
 var to,cc []netmail.Address
 for _,value:=range thread.Participants{
  addr,err:=netmail.ParseAddress(value);if err!=nil||ccSet[strings.ToLower(addr.Address)]{continue}
  if parsed,ok:=parseAddrIfAllowed(value,own,seen);ok{to=append(to,parsed)}
 }
 for _,value:=range thread.Cc{if parsed,ok:=parseAddrIfAllowed(value,own,seen);ok{cc=append(cc,parsed)}}
 if len(to)+len(cc)==0{return nil,nil,fmt.Errorf("new email has no recipients")}
 return to,cc,nil
}

func(ec *EmailClient)recordContactSend(ctx context.Context,msg *bridgev2.MatrixMessage,thread *email.EmailThread,messageID string)*bridgev2.MatrixMessageResponse{
 contact,_:=email.ContactFromPortal(msg.Portal.ID)
 nativeID:=email.ContactMessageID(messageID)
 root:=nativeID
 chain,err:=ec.Main.Contacts.Record(ctx,string(ec.UserLogin.ID),thread,messageID,contact,time.Now())
 if err!=nil{
  // SMTP has already accepted the email. Reporting a send failure here would
  // invite an unsafe duplicate retry. Keep the successful native send result.
  ec.UserLogin.Log.Error().Err(err).Msg("Email sent but contact reply context could not be saved")
  _=postErrorToPortal(ctx,ec.UserLogin.Bridge,msg.Portal,"Email sent","Reply context could not be saved. Do not resend; inspect the bridge journal.")
 }else{root=chain.RootID}
 return &bridgev2.MatrixMessageResponse{DB:&database.Message{ID:nativeID,SenderID:MakeUserID(ec.Email),Timestamp:time.Now(),ThreadRoot:root}}
}

// Compose creates a subject root inside the existing contact room. Typing in
// that Matrix thread sends the first email; this command itself sends no mail.
func fnContactCompose(ce *commands.Event,ec *EmailConnector){
 args,err:=parseComposeArgs(ce.RawArgs);if err!=nil{ce.Reply("%s",err);return}
 var client *EmailClient
 for _,login:=range ce.User.GetUserLogins(){if c,ok:=login.Client.(*EmailClient);ok{client=c;break}}
 if client==nil{ce.Reply("Connect an email account with !matrimail login first.");return}
 key:=networkid.PortalKey{ID:email.ContactPortalID(strings.ToLower(args.To)),Receiver:client.UserLogin.ID}
 portal,err:=ce.Bridge.GetPortalByKey(ce.Ctx,key);if err!=nil{ce.Reply("Could not open contact room: %s",err);return}
 info,err:=ec.contactChatInfo(key.ID);if err!=nil{ce.Reply("%s",err);return}
 if portal.MXID==""{if err=portal.CreateMatrixRoom(ce.Ctx,client.UserLogin,info);err!=nil{ce.Reply("Could not create contact room: %s",err);return}}
 draftID:="compose-"+uuid.NewString()
 thread:=&email.EmailThread{ThreadID:draftID,Subject:args.Subject,Participants:append([]string{strings.ToLower(args.To),client.Email},args.Cc...),Cc:args.Cc,IsDraft:true}
 chain,err:=ec.Contacts.Record(ce.Ctx,string(client.UserLogin.ID),thread,draftID,strings.ToLower(args.To),time.Now())
 if err!=nil{ce.Reply("Could not save draft context: %s",err);return}
 subject:=args.Subject;if subject==""{subject="(no subject)"}
 content:=&event.MessageEventContent{MsgType:event.MsgNotice,Body:"Subject: "+subject+"\nTo: "+args.To+"\nCc: "+strings.Join(args.Cc,", ")+"\nReply in this Matrix thread to send your email. Nothing has been sent yet."}
 mapping:=&database.Message{ID:chain.RootID,Room:key,SenderMXID:ce.Bridge.Bot.GetMXID(),Timestamp:time.Now(),ThreadRoot:chain.RootID}
 response,err:=ce.Bridge.Bot.SendMessage(ce.Ctx,portal.MXID,event.EventMessage,&event.Content{Parsed:content},&bridgev2.MatrixSendExtra{MessageMeta:mapping})
 if err==nil{mapping.MXID=response.EventID;err=ce.Bridge.DB.Message.Insert(ce.Ctx,mapping)}
 if err!=nil{ce.Reply("Could not create draft thread: %s. No email was sent.",err);return}
 ce.Reply("Draft ready in [%s](%s). Reply in the thread under ‘Subject: %s’ to send it. No email has been sent yet.",args.To,portal.MXID.URI().MatrixToURL(),subject)
}

func contactRoomOwnedBy(portal *bridgev2.Portal,login *bridgev2.UserLogin)bool{
 return portal!=nil&&login!=nil&&portal.MXID!=""&&portal.Receiver==login.ID&&
  (strings.HasPrefix(string(portal.ID),"thread:")||strings.HasPrefix(string(portal.ID),"contact:"))
}

// Repair only this bridge's own native portals. Existing pending invitations
// are accepted, but rooms explicitly left or banned are not force-joined.
func(ec *EmailConnector)repairContactRoom(ctx context.Context,portal *bridgev2.Portal,login *bridgev2.UserLogin)error{
 if !contactRoomOwnedBy(portal,login){return fmt.Errorf("not an owned Matrimail portal")}
 levels,err:=ec.Bridge.Matrix.GetPowerLevels(ctx,portal.MXID);if err!=nil{return err}
 changed:=false
 for _,kind:=range []event.Type{event.EventMessage,event.EventEncrypted}{
  if levels.Events==nil{levels.Events=map[string]int{}}
  if level,present:=levels.Events[kind.Type];!present||level!=0{levels.Events[kind.Type]=0;changed=true}
 }
 if changed{if _,err=ec.Bridge.Bot.SendState(ctx,portal.MXID,event.StatePowerLevels,"",&event.Content{Parsed:levels},time.Time{});err!=nil{return err}}
 if !ec.Config.AutoJoinRooms{return nil}
 membership,err:=ec.Bridge.Matrix.GetMemberInfo(ctx,portal.MXID,login.UserMXID);if err!=nil{return err}
 if membership==nil||membership.Membership!=event.MembershipInvite{return nil}
 puppet:=login.User.DoublePuppet(ctx);if puppet==nil{return fmt.Errorf("automatic Matrimail joining requires the owner-scoped double puppet")}
 return puppet.EnsureJoined(ctx,portal.MXID)
}

func(ec *EmailConnector)startContactRoomMaintenance(ctx context.Context){
 go func(){
  complete:=map[id.RoomID]bool{}
  ticker:=time.NewTicker(time.Minute);defer ticker.Stop()
  for{
   portals,err:=ec.Bridge.GetAllPortalsWithMXID(ctx)
   if err!=nil{ec.Bridge.Log.Warn().Err(err).Msg("Could not list Matrimail rooms for permission repair")}
   for _,portal:=range portals{
    if ctx.Err()!=nil{return};if complete[portal.MXID]{continue}
    login:=ec.Bridge.GetCachedUserLoginByID(portal.Receiver);if !contactRoomOwnedBy(portal,login){continue}
    attempt,cancel:=context.WithTimeout(ctx,30*time.Second)
    err:=ec.repairContactRoom(attempt,portal,login);cancel()
    if err!=nil{ec.Bridge.Log.Warn().Err(err).Msg("Matrimail room permission/join repair will retry")}else{complete[portal.MXID]=true}
   }
   select{case<-ctx.Done():return;case<-ticker.C:}
  }
 }()
}
