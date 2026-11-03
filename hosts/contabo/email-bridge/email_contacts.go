package email

// Contact rooms use their own namespace so retained mail can be copied from
// legacy per-subject rooms without deleting events or rewriting native mappings.
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
 s:=&ContactStore{DB:db,BridgeID:bridgeID}
 for _,query:=range []string{
  `CREATE TABLE IF NOT EXISTS contabo_email_chain (
   bridge_id TEXT NOT NULL, receiver TEXT NOT NULL, thread_id TEXT NOT NULL,
   contact TEXT NOT NULL, root_id TEXT NOT NULL, updated BIGINT NOT NULL, data TEXT NOT NULL,
   PRIMARY KEY (bridge_id,receiver,thread_id))`,
  `CREATE TABLE IF NOT EXISTS contabo_email_message (
   bridge_id TEXT NOT NULL, receiver TEXT NOT NULL, message_id TEXT NOT NULL,
   thread_id TEXT NOT NULL, data TEXT NOT NULL,
   PRIMARY KEY (bridge_id,receiver,message_id))`,
 } {if _,err:=db.ExecContext(ctx,query);err!=nil{return nil,err}}
 return s,nil
}

func ContactMessageID(raw string) networkid.MessageID {return networkid.MessageID("contact-email:"+RawEmailMessageID(raw))}
func RawEmailMessageID(raw string) string {
 for _,prefix:=range []string{"contact-email:","email:"}{if strings.HasPrefix(raw,prefix){return strings.TrimPrefix(raw,prefix)}}
 return strings.Trim(raw,"<>")
}
func ContactPortalID(contact string) networkid.PortalID {
 return networkid.PortalID("contact:"+base64.RawURLEncoding.EncodeToString([]byte(contact)))
}
func ContactFromPortal(portal networkid.PortalID)(string,error){
 if !strings.HasPrefix(string(portal),"contact:"){return "",fmt.Errorf("not a contact room")}
 decoded,err:=base64.RawURLEncoding.DecodeString(strings.TrimPrefix(string(portal),"contact:"))
 if err!=nil||len(decoded)==0{return "",fmt.Errorf("invalid contact room")}
 return string(decoded),nil
}
func canonicalContactAddress(value string)string{
 parsed,err:=mail.ParseAddress(value);if err!=nil{return ""};return strings.ToLower(parsed.Address)
}

// Incoming conversations are anchored to their first external sender. Sent-first
// conversations use their external recipient set. Never fold different accounts
// together, or strip address components such as plus-tags.
func ContactForEmail(parsed *ParsedEmail,selves []string)(string,error){
 own:=map[string]bool{};for _,value:=range selves{own[canonicalContactAddress(value)]=true}
 from:=canonicalContactAddress(parsed.From)
 if from!=""&&!own[from]{return from,nil}
 others:=map[string]bool{}
 for _,value:=range append(append([]string{},parsed.To...),parsed.Cc...){
  addr:=canonicalContactAddress(value);if addr!=""&&!own[addr]{others[addr]=true}
 }
 values:=make([]string,0,len(others));for value:=range others{values=append(values,value)};sort.Strings(values)
 if len(values)==0{if from!=""{return from,nil};return "",fmt.Errorf("email has no usable contact address")}
 return strings.Join(values,","),nil
}

func(s *ContactStore)GetChain(ctx context.Context,receiver,threadID string)(*ContactChain,error){
 var data string
 err:=s.DB.QueryRowContext(ctx,`SELECT data FROM contabo_email_chain WHERE bridge_id=$1 AND receiver=$2 AND thread_id=$3`,s.BridgeID,receiver,threadID).Scan(&data)
 if errors.Is(err,sql.ErrNoRows){return nil,nil};if err!=nil{return nil,err}
 var chain ContactChain;if err=json.Unmarshal([]byte(data),&chain);err!=nil{return nil,err};return &chain,nil
}
func(s *ContactStore)GetMessage(ctx context.Context,receiver,messageID string)(*ContactChain,error){
 var data string
 err:=s.DB.QueryRowContext(ctx,`SELECT data FROM contabo_email_message WHERE bridge_id=$1 AND receiver=$2 AND message_id=$3`,s.BridgeID,receiver,RawEmailMessageID(messageID)).Scan(&data)
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
 if thread==nil||thread.ThreadID==""||messageID==""{return nil,fmt.Errorf("missing email chain identity")}
 s.mu.Lock();defer s.mu.Unlock()
 tx,err:=s.DB.BeginTx(ctx,nil);if err!=nil{return nil,err};defer tx.Rollback()
 chain:=ContactChain{Contact:contact,RootID:ContactMessageID(messageID),Thread:thread}
 var oldContact,oldRoot string
 err=tx.QueryRowContext(ctx,`SELECT contact,root_id FROM contabo_email_chain WHERE bridge_id=$1 AND receiver=$2 AND thread_id=$3`,s.BridgeID,receiver,thread.ThreadID).Scan(&oldContact,&oldRoot)
 if err==nil{chain.Contact=oldContact;chain.RootID=networkid.MessageID(oldRoot)}else if !errors.Is(err,sql.ErrNoRows){return nil,err}
 if chain.Contact==""{return nil,fmt.Errorf("email chain has no contact")}
 data,err:=json.Marshal(chain);if err!=nil{return nil,err}
 _,err=tx.ExecContext(ctx,`INSERT INTO contabo_email_chain (bridge_id,receiver,thread_id,contact,root_id,updated,data)
 VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (bridge_id,receiver,thread_id) DO UPDATE SET
 updated=excluded.updated,data=excluded.data WHERE excluded.updated>=contabo_email_chain.updated`,
 s.BridgeID,receiver,thread.ThreadID,chain.Contact,string(chain.RootID),observed.UnixNano(),string(data))
 if err!=nil{return nil,err}
 _,err=tx.ExecContext(ctx,`INSERT INTO contabo_email_message (bridge_id,receiver,message_id,thread_id,data)
 VALUES ($1,$2,$3,$4,$5) ON CONFLICT (bridge_id,receiver,message_id) DO NOTHING`,
 s.BridgeID,receiver,RawEmailMessageID(messageID),thread.ThreadID,string(data))
 if err!=nil{return nil,err};if err=tx.Commit();err!=nil{return nil,err}
 // Return a detached snapshot; the upstream in-memory thread cache is mutable.
 var saved ContactChain;err=json.Unmarshal(data,&saved);return &saved,err
}
