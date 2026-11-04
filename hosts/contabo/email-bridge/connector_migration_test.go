package connector

import(
 "context"
 "database/sql"
 "path/filepath"
 "testing"
 "os"
 "strings"

 up "go.mau.fi/util/configupgrade"
 "gopkg.in/yaml.v3"
 _ "github.com/mattn/go-sqlite3"
)

func TestContaboLegacyCoverageRequiresEveryPartInOwnerContactRoom(t *testing.T){
 ctx:=context.Background()
 db,err:=sql.Open("sqlite3",filepath.Join(t.TempDir(),"mail.sqlite"));if err!=nil{t.Fatal(err)}
 defer db.Close()
 _,err=db.Exec(`CREATE TABLE message(
  bridge_id TEXT NOT NULL, id TEXT NOT NULL, part_id TEXT NOT NULL, mxid TEXT,
  room_id TEXT NOT NULL, room_receiver TEXT NOT NULL)`)
 if err!=nil{t.Fatal(err)}
 insert:=func(receiver,remote,part,mx,room string){
  t.Helper()
  if _,err:=db.Exec(`INSERT INTO message VALUES ('mail',?,?,?,?,?)`,remote,part,mx,room,receiver);err!=nil{t.Fatal(err)}
 }
 // Two separate old subject rooms refer to one contact room. Each needs
 // full coverage independently before its old room is marked as archived.
 insert("owner","email:first","text","$old1","thread:first")
 insert("owner","email:first","attachment","$old2","thread:first")
 insert("owner","email:second","text","$old3","thread:second")
 insert("owner","contact-v3-email:first","text","$new1","contact-v3:alice")
 insert("owner","contact-v3-email:second","text","$new3","contact-v3:alice")
 // Another user's mapping and a fake Matrix event must not count.
 insert("friend","contact-v3-email:first","attachment","$friend","contact-v3:alice")
 insert("owner","contact-v3-email:first","attachment","~fake:not-delivered","contact-v3:alice")
 check:=func(room string,wantMapped int){
  t.Helper()
  coverage,err:=legacyCoverageForDB(ctx,db,"mail",room,"owner")
  if err!=nil{t.Fatal(err)}
  if coverage.Total!=1||coverage.Mapped!=wantMapped||coverage.complete()!=(wantMapped==1){
   t.Fatalf("%s: unexpected coverage %#v",room,coverage)
  }
 }
 check("thread:first",0)
 check("thread:second",1)
 insert("owner","contact-v3-email:first","attachment","$new2","contact-v3:alice")
 check("thread:first",1)
 // The old room's messages may map to two target contact rooms because of
 // an unusual participant change, but each individual message's parts
 // must remain within one target portal.
 insert("owner","email:third","text","$old4","thread:third")
 insert("owner","email:third","attachment","$old5","thread:third")
 insert("owner","contact-v3-email:third","text","$new4","contact-v3:alice")
 insert("owner","contact-v3-email:third","attachment","$new5","contact-v3:bob")
 check("thread:third",0)
 // Counts alone are insufficient: a new attachment part with a different
 // PartID must never certify the original part.
 insert("owner","email:fourth","text","$old6","thread:fourth")
 insert("owner","email:fourth","attachment","$old7","thread:fourth")
 insert("owner","contact-v3-email:fourth","text","$new6","contact-v3:alice")
 insert("owner","contact-v3-email:fourth","other-attachment","$new7","contact-v3:alice")
 check("thread:fourth",0)
 insert("owner","contact-v3-email:fourth","attachment","$new8","contact-v3:alice")
 check("thread:fourth",1)
 // Previously misgrouped contact portals also need to be rebuilt.
 insert("owner","contact-email:previous","text","$old8","contact:misgrouped")
 insert("owner","contact-v3-email:previous","text","$new8","contact-v3:correct")
 check("contact:misgrouped",1)
}

func TestContaboContactRoutingSurvivesNetworkConfigUpgrade(t *testing.T){
 ec:=&EmailConnector{}
 example,_,networkUpgrader:=ec.GetConfig()
 if !strings.Contains(example,"contact_rooms: false") ||
    !strings.Contains(example,"auto_join_rooms: false"){
  t.Fatal("Matrimail example config must advertise both migration flags")
 }
 path:=filepath.Join(t.TempDir(),"config.yaml")
 if err:=os.WriteFile(path,[]byte("network:\n  contact_rooms: true\n  auto_join_rooms: true\n"),0600);err!=nil{t.Fatal(err)}
 fullExample:="network:\n  "+strings.ReplaceAll(strings.TrimSuffix(example,"\n"),"\n","\n  ")+"\n"
 upgrader:=up.MergeUpgraders(fullExample,&up.ProxyUpgrader{
  Target:networkUpgrader,Prefix:[]string{"network"},
 })
 upgraded,_,err:=up.Do(path,false,upgrader)
 if err!=nil{t.Fatal(err)}
 var result struct{Network Config `yaml:"network"`}
 if err=yaml.Unmarshal(upgraded,&result);err!=nil{t.Fatal(err)}
 if !result.Network.ContactRooms||!result.Network.AutoJoinRooms{
  t.Fatalf("Matrimail erased contact-room flags during config upgrade: %+v",result.Network)
 }
}
