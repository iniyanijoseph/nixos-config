package imap

import (
 "context"
 "errors"
 "os"
 "path/filepath"
 "reflect"
 "testing"
 "time"
)

func TestContaboMailBackfillResumesAfterFailureWithoutSkippingUID(t *testing.T){
 path:=filepath.Join(t.TempDir(),"cursor.json")
 var calls []uint32
 search:=func(after,until uint32,since time.Time)([]uint32,error){return []uint32{3,1,2},nil}
 first:=func(uid uint32)error{calls=append(calls,uid);if uid==2{return errors.New("Matrix mapping not confirmed")};return nil}
 count,err:=contaboBackfillMailbox(context.Background(),path,7,3,0,search,first,nil,0)
 if err==nil||count!=1||!reflect.DeepEqual(calls,[]uint32{1,2}){t.Fatalf("wrong failure progress: %d %v %v",count,calls,err)}
 var resumedAfter uint32
 resumeSearch:=func(after,until uint32,since time.Time)([]uint32,error){resumedAfter=after;if until!=3{t.Fatal("snapshot waterline moved on resume")};return []uint32{2,3},nil}
 count,err=contaboBackfillMailbox(context.Background(),path,7,99,0,resumeSearch,func(uid uint32)error{calls=append(calls,uid);return nil},nil,0)
 if err!=nil||count!=3||resumedAfter!=1||!reflect.DeepEqual(calls,[]uint32{1,2,2,3}){t.Fatalf("resume skipped/replayed success: %d %v %v",count,calls,err)}
 count,err=contaboBackfillMailbox(context.Background(),path,7,100,0,func(uint32,uint32,time.Time)([]uint32,error){t.Fatal("completed scan searched again");return nil,nil},first,nil,0)
 if err!=nil||count!=3{t.Fatal("completed retry failed",err)}
 info,_:=os.Stat(path);if info.Mode().Perm()!=0600{t.Fatal("private checkpoint has unsafe mode")}
}

func TestContaboMailBackfillRejectsUIDValidityChange(t *testing.T){
 path:=filepath.Join(t.TempDir(),"cursor.json")
 if err:=contaboSaveMailCursor(path,contaboMailCursor{Version:1,Validity:7,Waterline:5,After:2});err!=nil{t.Fatal(err)}
 _,err:=contaboBackfillMailbox(context.Background(),path,8,5,0,func(uint32,uint32,time.Time)([]uint32,error){t.Fatal("wrong mailbox was searched");return nil,nil},nil,nil,0)
 if err==nil{t.Fatal("UIDVALIDITY mismatch accepted")}
}

func TestContaboMailBackfillRetainsWindowAndStopsAtWaterline(t *testing.T){
 path:=filepath.Join(t.TempDir(),"cursor.json")
 since:=time.Date(2020,1,1,0,0,0,0,time.UTC)
 if err:=contaboSaveMailCursor(path,contaboMailCursor{Version:1,Validity:7,Waterline:5,Since:since});err!=nil{t.Fatal(err)}
 var processed []uint32
 _,err:=contaboBackfillMailbox(context.Background(),path,7,99,30,func(after,until uint32,got time.Time)([]uint32,error){if !got.Equal(since)||until!=5{t.Fatal("scope moved during retry")};return []uint32{6},nil},func(uid uint32)error{processed=append(processed,uid);return nil},nil,0)
 if err==nil||len(processed)!=0{t.Fatal("out-of-snapshot message processed")}
}

func TestContaboMailBackfillCancellationDoesNotAdvanceCursor(t *testing.T){
 path:=filepath.Join(t.TempDir(),"cursor.json");ctx,cancel:=context.WithCancel(context.Background());cancel()
 _,err:=contaboBackfillMailbox(ctx,path,7,10,0,func(uint32,uint32,time.Time)([]uint32,error){t.Fatal("cancelled import searched");return nil,nil},nil,nil,0)
 if err==nil{t.Fatal("cancelled import succeeded")}
}

func TestContaboMailMappingWaitRequiresNativeMapping(t *testing.T){
 calls:=0
 err:=contaboWaitForMailMapping(context.Background(),func()(bool,error){calls++;return calls==3,nil},time.Microsecond)
 if err!=nil||calls!=3{t.Fatal("mapping acknowledgement was not awaited")}
 ctx,cancel:=context.WithTimeout(context.Background(),time.Millisecond);defer cancel()
 if err=contaboWaitForMailMapping(ctx,func()(bool,error){return false,nil},time.Microsecond);err==nil{t.Fatal("missing mapping accepted")}
 if err=contaboWaitForMailMapping(context.Background(),func()(bool,error){return false,errors.New("database unavailable")},0);err==nil{t.Fatal("mapping lookup failure ignored")}
}
