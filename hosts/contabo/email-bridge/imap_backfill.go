package imap

// Explicit history import uses a separate authenticated IMAP connection. It
// never rewinds the live IDLE cursor, changes flags, or deletes source mail.
import (
 "context"
 "crypto/sha256"
 "encoding/json"
 "fmt"
 "os"
 "path/filepath"
 "sort"
 "syscall"
 "time"

 imaplib "github.com/emersion/go-imap/v2"
 "maunium.net/go/mautrix/bridgev2/networkid"
)

type contaboMailCursor struct {
 Version int `json:"version"`
 Validity uint32 `json:"uid_validity"`
 Waterline uint32 `json:"waterline"`
 After uint32 `json:"after"`
 Since time.Time `json:"since"`
 Processed int `json:"processed"`
}

func contaboWaitForMailMapping(ctx context.Context,lookup func()(bool,error),interval time.Duration)error{
 for{
  if err:=ctx.Err();err!=nil{return fmt.Errorf("waiting for native Matrix mapping: %w",err)}
  mapped,err:=lookup();if err!=nil{return err};if mapped{return nil}
  select{case<-ctx.Done():return fmt.Errorf("waiting for native Matrix mapping: %w",ctx.Err());case<-time.After(interval):}
 }
}

func(c *Client)contaboMappedMessage(ctx context.Context,message networkid.MessageID)(bool,error){
 mapping,err:=c.login.Bridge.DB.Message.GetFirstPartByID(ctx,c.login.ID,message)
 return mapping!=nil&&mapping.MXID!=""&&!mapping.HasFakeMXID(),err
}

func(c *Client)contaboWaitForMessage(ctx context.Context,message networkid.MessageID)error{
 ctx,cancel:=context.WithTimeout(ctx,2*time.Minute);defer cancel()
 return contaboWaitForMailMapping(ctx,func()(bool,error){return c.contaboMappedMessage(ctx,message)},100*time.Millisecond)
}

func contaboSaveMailCursor(path string, value contaboMailCursor) error {
 if err:=os.MkdirAll(filepath.Dir(path),0700);err!=nil{return err}
 file,err:=os.CreateTemp(filepath.Dir(path),".cursor-");if err!=nil{return err}
 temporary:=file.Name();defer os.Remove(temporary)
 if err=json.NewEncoder(file).Encode(value);err==nil{err=file.Sync()}
 closeErr:=file.Close();if err!=nil{return err};if closeErr!=nil{return closeErr}
 if err=os.Rename(temporary,path);err!=nil{return err}
 directory,err:=os.Open(filepath.Dir(path));if err!=nil{return err};defer directory.Close()
 return directory.Sync()
}

func contaboBackfillMailbox(ctx context.Context,path string,validity,waterline uint32,days int,
 search func(uint32,uint32,time.Time)([]uint32,error),process func(uint32)error,
 progress func(int,int),delay time.Duration)(int,error){
 cursor:=contaboMailCursor{Version:1,Validity:validity,Waterline:waterline}
 if days>0{cursor.Since=time.Now().AddDate(0,0,-days).Truncate(24*time.Hour)}
 raw,err:=os.ReadFile(path)
 if err==nil{
  if err=json.Unmarshal(raw,&cursor);err!=nil{return 0,fmt.Errorf("invalid mail history checkpoint")}
  if cursor.Version!=1||cursor.Validity!=validity||cursor.After>cursor.Waterline{return 0,fmt.Errorf("mailbox UIDVALIDITY or checkpoint changed; checkpoint retained for review")}
 }else if !os.IsNotExist(err){return 0,err}else if err=contaboSaveMailCursor(path,cursor);err!=nil{return 0,err}
 if cursor.After>=cursor.Waterline{return cursor.Processed,nil}
 if err=ctx.Err();err!=nil{return cursor.Processed,err}
 uids,err:=search(cursor.After,cursor.Waterline,cursor.Since);if err!=nil{return cursor.Processed,err}
 sort.Slice(uids,func(i,j int)bool{return uids[i]<uids[j]})
 total:=cursor.Processed+len(uids)
 if progress!=nil{progress(cursor.Processed,total)}
 for _,uid:=range uids{
  if uid<=cursor.After{continue}
  if uid>cursor.Waterline{return cursor.Processed,fmt.Errorf("history search crossed frozen UID waterline")}
  if err=ctx.Err();err!=nil{return cursor.Processed,err}
  if err=process(uid);err!=nil{return cursor.Processed,err}
  // process waits for a native Matrix mapping before this checkpoint moves.
  cursor.After=uid;cursor.Processed++
  if err=contaboSaveMailCursor(path,cursor);err!=nil{return cursor.Processed,err}
  if progress!=nil{progress(cursor.Processed,total)}
  if delay>0{select{case<-ctx.Done():return cursor.Processed,ctx.Err();case<-time.After(delay):}}
 }
 cursor.After=cursor.Waterline
 return cursor.Processed,contaboSaveMailCursor(path,cursor)
}

// ContaboBackfill imports all retained mail in the selected folders, or the
// requested day window. Drafts are skipped by the existing native processor.
// A repeated command resumes its frozen snapshot, not a moving date window.
func(c *Client)ContaboBackfill(ctx context.Context,mailboxes []string,days int,progress func(string,int,int))(int,error){
 if err:=ctx.Err();err!=nil{return 0,err}
 if c.login==nil||c.processor==nil{return 0,fmt.Errorf("email account is not ready for history import")}
 worker,err:=NewClient(c.Email,c.Username,c.Password,c.login,c.log,c.sanitized,c.secret,0,0,0,nil)
 if err!=nil{return 0,err}
 worker.Host=c.Host;worker.Port=c.Port;worker.TLS=c.TLS
 worker.UseXOAUTH2=c.UseXOAUTH2;worker.AccessToken=c.AccessToken;worker.TokenProvider=c.TokenProvider
 worker.SetProcessor(c.processor)
 if err=worker.Connect();err!=nil{return 0,err}
 defer worker.Disconnect()
 // Closing this worker's connection unblocks any IMAP command on cancellation.
 stopClose:=context.AfterFunc(ctx,func(){worker.mu.RLock();cli:=worker.client;worker.mu.RUnlock();if cli!=nil{cli.Close()}})
 defer stopClose()
 total:=0
 for _,mailbox:=range mailboxes{
  selected,err:=worker.client.Select(mailbox,&imaplib.SelectOptions{ReadOnly:true}).Wait()
  if err!=nil{return total,fmt.Errorf("history mailbox select failed: %w",err)}
  if selected.UIDValidity==0||selected.UIDNext==0{return total,fmt.Errorf("mailbox did not supply a stable UIDVALIDITY/UIDNEXT")}
  key:=sha256.Sum256([]byte(string(c.login.UserMXID)+"\x00"+c.Email+"\x00"+c.Host+fmt.Sprintf(":%d",c.Port)+"\x00"+mailbox+fmt.Sprintf("\x00%d",days)))
  path:=filepath.Join("contabo-backfill",fmt.Sprintf("%x.json",key))
  processed,err:=contaboBackfillMailbox(ctx,path,selected.UIDValidity,uint32(selected.UIDNext-1),days,
   func(after,until uint32,since time.Time)([]uint32,error){
    set:=imaplib.UIDSet{};set.AddRange(imaplib.UID(after+1),imaplib.UID(until))
    criteria:=&imaplib.SearchCriteria{UID:[]imaplib.UIDSet{set},Since:since}
    result,err:=worker.client.UIDSearch(criteria,nil).Wait();if err!=nil{return nil,err}
    values:=result.AllUIDs();uids:=make([]uint32,len(values));for i,uid:=range values{uids[i]=uint32(uid)}
    return uids,nil
   },func(uid uint32)error{
    var disk syscall.Statfs_t
    if err:=syscall.Statfs(".",&disk);err!=nil{return err}
    if uint64(disk.Bavail)*uint64(disk.Bsize)<5*1024*1024*1024{return fmt.Errorf("mail history paused: less than 5 GiB free")}
    return worker.processMessageWith(ctx,worker.client,imaplib.UID(uid),mailbox,true)
   },func(done,count int){if progress!=nil{progress(mailbox,done,count)}},500*time.Millisecond)
  total+=processed
  if err!=nil{return total,err}
 }
 return total,nil
}
