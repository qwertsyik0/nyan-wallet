"use strict";
const fs=require("node:fs");
const vm=require("node:vm");
const assert=require("node:assert/strict");

const script=fs.readFileSync("elections.js","utf8");
const page=fs.readFileSync("elections.html","utf8");
const style=fs.readFileSync("elections.css","utf8");
const markerStart="function validateParty(form){";
const markerEnd="\nfunction button(";
const start=script.indexOf(markerStart),end=script.indexOf(markerEnd,start);
assert(start>=0&&end>start,"Party validation function missing");
const validator=script.slice(start,end);
assert(page.includes('id="el-create" class="el-form" novalidate'),"Native validation might silently cancel submit");
assert(page.includes('id="el-form-feedback"'),"Missing visible error location");
assert(page.includes('id="el-program-counter"'),"Missing live program counter");
assert(style.includes(".el-form-feedback{"),"Missing error feedback style");
assert(script.includes('await mutate("/parties",payload);'),"Valid submissions do not reach API");
assert(script.includes('else submitParty(form);'),"Submit event not routed into validation");

function validate(values,image=null) {
  let feedback=null,focused=null;
  const fields=Object.fromEntries(Object.entries(values).map(([name,value])=>[name,{value,focus(){focused=name;}}]));
  const context={
    selectedEmblem:image,
    formFeedback(message){feedback=message;},
    $(id){return{focus(){focused=id;}};},
  };
  vm.createContext(context);
  vm.runInContext(validator,context);
  const result=context.validateParty({
    elements:{namedItem(name){return fields[name];}},
  });
  return {result:result?JSON.parse(JSON.stringify(result)):null,feedback,focused};
}
const base={name:"Партия Лапы",short_name:"ПЛ",program:"Предлагаем честные выборы, новые правила и интересные события."};
let v=validate({...base,program:"тест"});
assert.equal(v.result,null);
assert(v.feedback.includes("минимум 30"));
assert.equal(v.focused,"program");
v=validate({...base,name:"A"});
assert.equal(v.result,null);
assert.equal(v.focused,"name");
v=validate({...base,short_name:"?"});
assert.equal(v.result,null);
assert.equal(v.focused,"short_name");
v=validate(base,{type:"image/jpeg",size:3*1024*1024});
assert.equal(v.result,null);
assert(v.feedback.includes("2 МБ"));
v=validate(base);
assert.equal(v.result.name,"Партия Лапы");
assert.equal(v.result.short_name,"ПЛ");
assert.equal(v.result.program,base.program);
assert.equal(v.feedback,"");
assert(script.includes('if(Array.isArray(detail))'),"Server validation errors not displayed");
assert(script.includes("Отправляем заявку"),"No progress feedback on slow image uploads");
console.log("OK: invalid forms show exact reason; valid party gets submitted, including optional image");
