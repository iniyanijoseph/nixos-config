package email

// Version 3 uses new native room/message IDs and chain tables. This allows a
// complete side-by-side replay into correctly grouped rooms while old thread:
// and contact: Matrix rooms remain readable until strictly verified for removal.
import (
 "context"
 "database/sql"
 "encoding/base64"
 "encoding/json"
 "errors"
 "fmt"
 "net/mail"
 "sort"
 "strings"
 "sync"
 "time"

 "maunium.net/go/mautrix/bridgev2/networkid"
)

type ContactStore struct { DB *sql.DB; BridgeID string; mu sync.Mutex }
type ContactChain struct {
 Contact string `json:"contact"`
 RootID networkid.MessageID `json:"root_id"`
 Thread *EmailThread `json:"thread"`
}

func NewContactStore(ctx context.Context, db *sql.DB, bridgeID string)(*ContactStore,error){
 if db==nil{return nil,fmt.Errorf("contact email database is unavailable")}
 s:=&ContactStore{DB:db,BridgeID:bridgeID}
 for _,query:=range []string{
  `CREATE TABLE IF NOT EXISTS contabo_email_chain_v3 (
   bridge_id TEXT NOT NULL, receiver TEXT NOT NULL, thread_id TEXT NOT NULL,
   contact TEXT NOT NULL, root_id TEXT NOT NULL, updated BIGINT NOT NULL, data TEXT NOT NULL,
   PRIMARY KEY (bridge_id,receiver,thread_id))`,
  `CREATE TABLE IF NOT EXISTS contabo_email_message_v3 (
   bridge_id TEXT NOT NULL, receiver TEXT NOT NULL, message_id TEXT NOT NULL,
   thread_id TEXT NOT NULL, data TEXT NOT NULL,
   PRIMARY KEY (bridge_id,receiver,message_id))`,
 } {if _,err:=db.ExecContext(ctx,query);err!=nil{return nil,err}}
 return s,nil
}

func ContactMessageID(raw string) networkid.MessageID {return networkid.MessageID("contact-v3-email:"+RawEmailMessageID(raw))}
func RawEmailMessageID(raw string) string {
 for _,prefix:=range []string{"contact-v3-email:","contact-email:","email:"}{if strings.HasPrefix(raw,prefix){return strings.TrimPrefix(raw,prefix)}}
 return strings.Trim(raw,"<>")
}
func ContactPortalID(contact string) networkid.PortalID {
 return networkid.PortalID("contact-v3:"+base64.RawURLEncoding.EncodeToString([]byte(contact)))
}
func ContactFromPortal(portal networkid.PortalID)(string,error){
 if !strings.HasPrefix(string(portal),"contact-v3:"){return "",fmt.Errorf("not a contact room")}
 decoded,err:=base64.RawURLEncoding.DecodeString(strings.TrimPrefix(string(portal),"contact-v3:"))
 if err!=nil||len(decoded)==0{return "",fmt.Errorf("invalid contact room")}
 return string(decoded),nil
}
func canonicalContactAddress(value string)string{
 parsed,err:=mail.ParseAddress(value);if err!=nil{return ""};return strings.ToLower(parsed.Address)
}

// Public Gmail addresses are case-insensitive, dot-insensitive and use
// plus-addressing. This is *only* for excluding the owner's own aliases
// from a room key; never rewrite external recipients or outgoing headers.
func gmailOwnerKey(value string)string{
 parts:=strings.Split(value,"@")
 if len(parts)!=2{return value}
 domain:=parts[1]
 if domain!="gmail.com"&&domain!="googlemail.com"{return value}
 local:=strings.SplitN(parts[0],"+",2)[0]
 return strings.ReplaceAll(local,".","")+"@gmail.com"
}

func IsOwnContactAddress(raw string,selves []string)bool{
 addr:=canonicalContactAddress(raw)
 if addr==""{return false}
 key:=gmailOwnerKey(addr)
 for _,self:=range selves{
  if own:=canonicalContactAddress(self);own!=""&&gmailOwnerKey(own)==key{return true}
 }
 return false
}

// A direct exchange maps to one contact room; a reply-all exchange maps to
// a group room named by the sorted external participants. Exclude all of the
// owner's configured addresses/aliases, preserve plus-tags, and never use the
// sender alone when a third party is on To or Cc. Once a thread is recorded,
// Record freezes its original room, even when later replies add/remove people.
func ContactForEmail(parsed *ParsedEmail,selves []string)(string,error){
 own:=map[string]bool{};for _,value:=range selves{if addr:=canonicalContactAddress(value);addr!=""{own[gmailOwnerKey(addr)]=true}}
 from:=canonicalContactAddress(parsed.From)
 others:=map[string]bool{}
 for _,value:=range append(append([]string{parsed.From},parsed.To...),parsed.Cc...){
  addr:=canonicalContactAddress(value);if addr!=""&&!own[gmailOwnerKey(addr)]{others[addr]=true}
 }
 values:=make([]string,0,len(others));for value:=range others{values=append(values,value)};sort.Strings(values)
 if len(values)>0{return strings.Join(values,","),nil}
 // Malformed, addressless, Bcc-only or system-generated mail must not stop
 // an entire resumable import. Route these to the owner's self room rather
 // than inventing an external recipient, joining unrelated mail by subject,
 // or silently discarding the source message. Record() retains an already
 // established chain's room when this is a reply with missing headers.
 // If every address belongs to the owner (including Gmail's plus/dot
 // aliases), use the stable primary account room instead of making one
 // self-only room for each tagged variant of the sender.
 if from!=""&&own[gmailOwnerKey(from)]{
  for _,self:=range selves{if addr:=canonicalContactAddress(self);addr!=""{return addr,nil}}
 }
 if from!=""{return from,nil}
 for _,self:=range selves{if addr:=canonicalContactAddress(self);addr!=""{return addr,nil}}
 return "",fmt.Errorf("email account has no usable own address for an addressless message")
}

func(s *ContactStore)GetChain(ctx context.Context,receiver,threadID string)(*ContactChain,error){
 var data string
 err:=s.DB.QueryRowContext(ctx,`SELECT data FROM contabo_email_chain_v3 WHERE bridge_id=$1 AND receiver=$2 AND thread_id=$3`,s.BridgeID,receiver,threadID).Scan(&data)
 if errors.Is(err,sql.ErrNoRows){return nil,nil};if err!=nil{return nil,err}
 var chain ContactChain;if err=json.Unmarshal([]byte(data),&chain);err!=nil{return nil,err};return &chain,nil
}
func(s *ContactStore)GetMessage(ctx context.Context,receiver,messageID string)(*ContactChain,error){
 var data string
 err:=s.DB.QueryRowContext(ctx,`SELECT data FROM contabo_email_message_v3 WHERE bridge_id=$1 AND receiver=$2 AND message_id=$3`,s.BridgeID,receiver,RawEmailMessageID(messageID)).Scan(&data)
 if errors.Is(err,sql.ErrNoRows){return nil,nil};if err!=nil{return nil,err}
 var chain ContactChain;if err=json.Unmarshal([]byte(data),&chain);err!=nil{return nil,err};return &chain,nil
}
func(s *ContactStore)ResolveThread(ctx context.Context,receiver,messageID string)(string,bool){
 chain,err:=s.GetMessage(ctx,receiver,messageID)
 if err!=nil||chain==nil||chain.Thread==nil{return "",false};return chain.Thread.ThreadID,true
}

// Record freezes the room/root on first sight, saves each message's own reply
// context, and updates the chain tail only for chronologically newer messages.
// An older backfill must not overwrite current recipients or the quote body.
func(s *ContactStore)Record(ctx context.Context,receiver string,thread *EmailThread,messageID,contact string,observed time.Time)(*ContactChain,error){
 return s.RecordWithParents(ctx,receiver,thread,messageID,contact,observed,nil)
}

// RecordWithParents uses exact RFC In-Reply-To and References links before
// trusting an inferred in-memory ThreadID. The source IMAP replay may observe
// a reply before its root (or after cache eviction), and the two would
// otherwise produce separate direct/group rooms. Never merge independent
// threads based merely on shared participants or matching subjects.
func(s *ContactStore)RecordWithParents(ctx context.Context,receiver string,thread *EmailThread,
 messageID,contact string,observed time.Time,parents []string)(*ContactChain,error){
 if thread==nil||thread.ThreadID==""||messageID==""{return nil,fmt.Errorf("missing email chain identity")}
 s.mu.Lock();defer s.mu.Unlock()
 tx,err:=s.DB.BeginTx(ctx,nil);if err!=nil{return nil,err};defer tx.Rollback()
 // IMAP may expose the *same* RFC Message-ID in INBOX and All Mail, and
 // after reconnect the upstream thread cache can assign a different thread
 // identity. The message's previously persisted room is authoritative:
 // never create a second chain/room for one already-routed source email.
 var existing string
 err=tx.QueryRowContext(ctx,`SELECT data FROM contabo_email_message_v3
  WHERE bridge_id=$1 AND receiver=$2 AND message_id=$3`,
  s.BridgeID,receiver,RawEmailMessageID(messageID)).Scan(&existing)
 if err==nil{
  var saved ContactChain
  if err=json.Unmarshal([]byte(existing),&saved);err!=nil{return nil,fmt.Errorf("decode existing email mapping: %w",err)}
  if saved.Contact==""||saved.RootID==""||saved.Thread==nil{
   return nil,fmt.Errorf("incomplete existing email contact mapping")
  }
  return &saved,nil
 }
 if !errors.Is(err,sql.ErrNoRows){return nil,err}
 // Link back to any previously persisted message in the same login.
 // Prefer the immediate parent, then the nearest surviving ancestor;
 // a distinct thread with merely overlapping CCs is never combined.
 for _,raw:=range parents{
  raw=RawEmailMessageID(raw)
  if raw==""||raw==RawEmailMessageID(messageID){continue}
  var parentData string
  e:=tx.QueryRowContext(ctx,`SELECT data FROM contabo_email_message_v3
     WHERE bridge_id=$1 AND receiver=$2 AND message_id=$3`,
     s.BridgeID,receiver,raw).Scan(&parentData)
  if errors.Is(e,sql.ErrNoRows){continue}
  if e!=nil{return nil,e}
  var parent ContactChain
  if e=json.Unmarshal([]byte(parentData),&parent);e!=nil{return nil,e}
  if parent.Contact==""||parent.RootID==""||parent.Thread==nil||parent.Thread.ThreadID==""{
   return nil,fmt.Errorf("incomplete RFC parent contact mapping")
  }
  // The shared cached thread is mutable. Never change its ThreadID in
  // place, since unrelated message processing could observe that change.
  copyThread:=*thread
  copyThread.ThreadID=parent.Thread.ThreadID
  thread=&copyThread
  contact=parent.Contact
  break
 }
 chain:=ContactChain{Contact:contact,RootID:ContactMessageID(messageID),Thread:thread}
 var oldContact,oldRoot string
 err=tx.QueryRowContext(ctx,`SELECT contact,root_id FROM contabo_email_chain_v3 WHERE bridge_id=$1 AND receiver=$2 AND thread_id=$3`,s.BridgeID,receiver,thread.ThreadID).Scan(&oldContact,&oldRoot)
 if err==nil{chain.Contact=oldContact;chain.RootID=networkid.MessageID(oldRoot)}else if !errors.Is(err,sql.ErrNoRows){return nil,err}
 if chain.Contact==""{return nil,fmt.Errorf("email chain has no contact")}
 data,err:=json.Marshal(chain);if err!=nil{return nil,err}
 _,err=tx.ExecContext(ctx,`INSERT INTO contabo_email_chain_v3 (bridge_id,receiver,thread_id,contact,root_id,updated,data)
 VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (bridge_id,receiver,thread_id) DO UPDATE SET
 updated=excluded.updated,data=excluded.data WHERE excluded.updated>=contabo_email_chain_v3.updated`,
 s.BridgeID,receiver,thread.ThreadID,chain.Contact,string(chain.RootID),observed.UnixNano(),string(data))
 if err!=nil{return nil,err}
 _,err=tx.ExecContext(ctx,`INSERT INTO contabo_email_message_v3 (bridge_id,receiver,message_id,thread_id,data)
 VALUES ($1,$2,$3,$4,$5) ON CONFLICT (bridge_id,receiver,message_id) DO NOTHING`,
 s.BridgeID,receiver,RawEmailMessageID(messageID),thread.ThreadID,string(data))
 if err!=nil{return nil,err};if err=tx.Commit();err!=nil{return nil,err}
 // Return a detached snapshot; the upstream in-memory thread cache is mutable.
 var saved ContactChain;err=json.Unmarshal(data,&saved);return &saved,err
}
