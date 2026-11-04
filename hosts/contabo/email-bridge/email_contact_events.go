package email

import (
 "context"
 "fmt"
 "html"
 "strings"

 "maunium.net/go/mautrix/bridgev2"
 "maunium.net/go/mautrix/bridgev2/networkid"
 "maunium.net/go/mautrix/event"
)

func(p *Processor)prepareContactMessage(ctx context.Context,message *EmailMessage,login *bridgev2.UserLogin)error{
 if p.Contacts==nil{return nil}
 selves:=[]string{strings.TrimPrefix(string(login.ID),"email:")}
 if p.aliasResolver!=nil{selves=append(selves,p.aliasResolver(string(login.ID))...)}
 contact,err:=ContactForEmail(message.ParsedEmail,selves);if err!=nil{return err}
 var parentIDs []string
 if !isForwardedMessage(message.ParsedEmail){
  if message.ParsedEmail.InReplyTo!=""{parentIDs=append(parentIDs,message.ParsedEmail.InReplyTo)}
  for i:=len(message.ParsedEmail.References)-1;i>=0;i--{
   parentIDs=append(parentIDs,message.ParsedEmail.References[i])
  }
 }
 chain,err:=p.Contacts.RecordWithParents(ctx,string(login.ID),message.Thread,message.ParsedEmail.MessageID,contact,message.Timestamp,parentIDs)
 if err!=nil{return fmt.Errorf("persist email contact routing: %w",err)}
 message.PortalKey=networkid.PortalKey{ID:ContactPortalID(chain.Contact),Receiver:login.ID}
 message.MessageID=ContactMessageID(message.ParsedEmail.MessageID)
 message.ContactRoot=chain.RootID
 return nil
}

func(e *EmailMatrixEvent)applyContactRelations(cm *bridgev2.ConvertedMessage){
 if cm==nil||e.emailMessage.ContactRoot==""{return}
 root:=e.emailMessage.ContactRoot;cm.ThreadRoot=&root
 if root==e.GetID(){
  // Keep the subject visible in the room's main timeline and thread picker.
  for _,part:=range cm.Parts{
   if part.Content!=nil&&(part.Content.MsgType==event.MsgText||part.Content.MsgType==event.MsgNotice){
    subject:=e.emailMessage.Subject;if subject==""{subject="(no subject)"}
    part.Content.Body="Subject: "+subject+"\n\n"+part.Content.Body
    if part.Content.Format==event.FormatHTML{part.Content.FormattedBody="<p><strong>Subject: "+html.EscapeString(subject)+"</strong></p>"+part.Content.FormattedBody}
    break
   }
  }
 }
}
