package main

import (
 "database/sql"
 "encoding/json"
 "testing"
)

func TestContaboArchiveOrderingAndChannelIsolation(t *testing.T) {
 db,err:=sql.Open("sqlite3",":memory:"); if err!=nil {t.Fatal(err)}; defer db.Close()
 db.SetMaxOpenConns(1)
 _,err=db.Exec("CREATE TABLE messages(channel_id TEXT,id TEXT,json TEXT)"); if err!=nil {t.Fatal(err)}
 ids:=[]string{"100","9","9223372036854775808","10"}
 for _,id:=range ids {
  raw,_:=json.Marshal(map[string]interface{}{"id":id,"channel_id":"123","author":map[string]string{"id":"456"}})
  if _,err=db.Exec("INSERT INTO messages VALUES(?,?,?)","123",id,string(raw));err!=nil {t.Fatal(err)}
 }
 db.Exec("INSERT INTO messages VALUES('other','11','{}')")
 tx,err:=db.Begin(); if err!=nil {t.Fatal(err)}; defer tx.Rollback()
 rows,err:=contaboArchiveBatch(tx,"123",""); if err!=nil {t.Fatal(err)}
 want:=[]string{"9","10","100","9223372036854775808"}
 if len(rows)!=len(want) {t.Fatalf("wrong count: %d",len(rows))}
 for i,row:=range rows {if row.ID!=want[i] {t.Fatalf("wrong order at %d",i)}}
 rows,err=contaboArchiveBatch(tx,"123","100"); if err!=nil {t.Fatal(err)}
 if len(rows)!=1 || rows[0].ID!=want[3] {t.Fatal("resume cursor lost an unsigned snowflake")}
}

func TestContaboArchiveRejectsMismatchedSource(t *testing.T) {
 db,err:=sql.Open("sqlite3",":memory:"); if err!=nil {t.Fatal(err)}; defer db.Close()
 db.Exec("CREATE TABLE messages(channel_id TEXT,id TEXT,json TEXT)")
 db.Exec(`INSERT INTO messages VALUES('123','100','{"id":"100","channel_id":"other","author":{"id":"456"}}')`)
 tx,err:=db.Begin(); if err!=nil {t.Fatal(err)}; defer tx.Rollback()
 if _,err=contaboArchiveBatch(tx,"123","");err==nil {t.Fatal("invalid archive was accepted")}
}
