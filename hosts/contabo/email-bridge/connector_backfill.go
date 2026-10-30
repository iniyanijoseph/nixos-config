package connector

import (
 "context"
 "strconv"
 "strings"
 "sync"

 "maunium.net/go/mautrix/bridgev2/commands"
)

var contaboMailJobs sync.Map

func fnContaboBackfill(ce *commands.Event,connector *EmailConnector){
 days:=30
 if len(ce.Args)>0{
  if ce.Args[0]=="all"{days=0}else{
   parsed,err:=strconv.Atoi(ce.Args[0]);if err!=nil||parsed<1||parsed>36500{ce.Reply("Usage: !matrimail backfill [days|all] [email]");return};days=parsed
  }
 }
 filter:="";if len(ce.Args)>1{filter=ce.Args[1]};if len(ce.Args)>2{ce.Reply("Usage: !matrimail backfill [days|all] [email]");return}
 var account *EmailClient
 for _,login:=range ce.User.GetUserLogins(){
  client,ok:=login.Client.(*EmailClient);if !ok||client==nil||client.IMAPClient==nil{continue}
  if filter!=""&&!strings.EqualFold(filter,client.Email){continue}
  if account!=nil{ce.Reply("Choose one account: !matrimail backfill all your@email.com");return}
  account=client
 }
 if account==nil{ce.Reply("No matching IMAP account is connected. Complete !matrimail login first. OAuth modify-mode uses !matrimail backlog instead.");return}
 imapClient:=account.IMAPClient
 key:=string(account.UserLogin.ID)
 if _,busy:=contaboMailJobs.LoadOrStore(key,true);busy{ce.Reply("Email history import is already running for this account. Progress is posted here.");return}
 folders:=append([]string(nil),account.MonitoredFolders...);if len(folders)==0{folders=[]string{"INBOX"}}
 ce.Reply("Starting resumable email history import for %s in %d selected folder(s). Original message dates are retained. Existing mappings are reused; source mail is read-only.",account.Email,len(folders))
 go func(){
  defer contaboMailJobs.Delete(key)
  defer func(){if failure:=recover();failure!=nil{connector.Bridge.Log.Error().Interface("failure",failure).Msg("Email backfill stopped after panic");ce.Reply("Email history import stopped unexpectedly. Checkpoints retained; inspect the private Matrimail journal.")}}()
  lastFolder:="";lastDone:=-1
  ctx,cancel:=context.WithCancel(account.ctx);defer cancel()
  count,err:=imapClient.ContaboBackfill(ctx,folders,days,func(folder string,done,total int){
   if folder!=lastFolder||done==total||done-lastDone>=50{ce.Reply("Email history %s: %d/%d processed (including existing mappings and skipped drafts).",folder,done,total);lastFolder=folder;lastDone=done}
  })
  if err!=nil{connector.Bridge.Log.Error().Err(err).Msg("Email history import paused");ce.Reply("Email history import paused after %d processed messages. Checkpoints retained. Repeat the same backfill command to resume; inspect the private Matrimail journal for the error.",count);return}
  ce.Reply("Email history scan completed: %d processed messages in the selected folders. Existing mappings and skipped drafts are included. Source mailbox unchanged; attachment parity has not been independently audited.",count)
 }()
}
