"use client";


import { useEffect, useMemo, useRef, useState } from "react";

import { Activity, Archive, Bot, Bug, Check, CheckCircle2, ChevronDown, ChevronRight, CircleDot, Clock3, Database, FileCheck2, Fingerprint, Folder, HardDrive, History, Home, Keyboard, Maximize2, MessageSquareText, Minus, Power, RefreshCw, RotateCcw, Search, ServerCog, Settings, Shield, ShieldCheck, Sparkles, Terminal, Trash2, Wrench, X, XCircle, Zap } from "lucide-react";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";


type State="active"|"unresolved"|"resolved-unverified"|"resolved-verified"|"user-open"|"user-resolved"|"snoozed-session"|"snoozed-permanent";

type Major="all"|"detected"|"user"|"snoozed";
type ThemeMode="light"|"dark"|"system";
type VisualSettings={theme:ThemeMode;font:string;scale:number;contrast:boolean};
type PurgeRecord={id:string;issueId:string;issue:string;observedAt:string;type:string};

type Issue={id:string;
state:State;
icon:typeof Activity;
title:string;
belief:string;
severity:"High"|"Medium"|"Low";
confidence:number;
first:string;
last:string;
count:number;
action:string;
source:string;
inference:string;
bucket:string;
responded:boolean;
note?:string;
failed?:boolean;
upstream?:boolean;
validated?:boolean;
ambiguous?:boolean;
userReported?:boolean};

const issues:Issue[]=[
 {id:"app",state:"active",icon:XCircle,title:"Notes closes just after opening",belief:"Notes has been launched repeatedly, but it stops before its window can remain open.",severity:"High",confidence:96,first:"Today, 8:14 AM",last:"12 minutes ago",count:9,action:"Repair recommended",source:"Guardian observed 9 launches followed by the same early exit within 3 seconds.",inference:"The application is likely failing during startup, rather than being closed normally.",bucket:"Actively Happening",responded:false,failed:true},
 {id:"service",state:"active",icon:ServerCog,title:"Backup service keeps restarting",belief:"The backup helper has restarted 18 times since this computer was turned on.",severity:"Medium",confidence:99,first:"Today, 7:42 AM",last:"4 minutes ago",count:18,action:"Investigation recommended",source:"Guardian observed 18 starts and unexpected stops during this boot.",inference:"The service is caught in a restart loop and is unlikely to complete a backup.",bucket:"Actively Happening",responded:false,upstream:true},
 {id:"keyboard",state:"unresolved",icon:Keyboard,title:"USB keyboard connection is unstable",belief:"The keyboard has disconnected and returned several times without being unplugged.",severity:"Medium",confidence:88,first:"Yesterday, 4:31 PM",last:"38 minutes ago",count:14,action:"Watching for a pattern",source:"Guardian observed the same USB input device disappear and reconnect 14 times.",inference:"A cable, hub, power-saving setting, or device fault may be interrupting the connection.",bucket:"Unresolved · Week",responded:true,ambiguous:true},
 {id:"wifi",state:"unresolved",icon:Activity,title:"Wireless connection briefly pauses",belief:"Internet access has paused twice, but Guardian does not yet have enough evidence to identify the cause.",severity:"Low",confidence:64,first:"Yesterday, 9:12 PM",last:"5 hours ago",count:2,action:"No action yet",source:"Guardian observed two short losses of network reachability.",inference:"The cause may be the router, signal conditions, or this computer. Evidence is incomplete.",bucket:"Unresolved · Session",responded:true,ambiguous:true},
 {id:"browser",state:"user-open",icon:MessageSquareText,title:"Browser freezes after video calls",belief:"You reported that the browser becomes unresponsive after some video calls.",severity:"Medium",confidence:52,first:"Sep 11, 2:20 PM",last:"Yesterday",count:3,action:"Needs correlation",source:"Three user-reported occurrences share the same application and activity.",inference:"Memory pressure may be involved, but Guardian has not observed a repeatable system signature yet.",bucket:"User Reported · Unresolved",responded:true,userReported:true,ambiguous:true},
 {id:"wallpaper",state:"snoozed-session",icon:HardDrive,title:"Wallpaper source is unavailable",belief:"The selected wallpaper lives on an external drive that is currently disconnected.",severity:"Low",confidence:100,first:"Aug 29",last:"Today, 7:43 AM",count:23,action:"Snoozed for this session",source:"Guardian observed that the wallpaper file path is unavailable when the external drive is absent.",inference:"This is intentional and does not currently affect login or the desktop shell.",bucket:"Snoozed · Session",responded:true,note:"The wallpaper drive is intentionally disconnected most of the time."},
 {id:"bluetooth",state:"snoozed-permanent",icon:ShieldCheck,title:"Bluetooth is intentionally disabled",belief:"Bluetooth remains switched off by your choice.",severity:"Low",confidence:100,first:"Aug 18",last:"Today, 7:42 AM",count:31,action:"Accepted permanently",source:"Guardian observed Bluetooth disabled across 31 checks.",inference:"The condition matches your saved preference and has no observed impact.",bucket:"Snoozed · Permanent",responded:true},
 {id:"audio",state:"resolved-verified",icon:CheckCircle2,title:"Headphones no longer lose audio",belief:"The original audio dropout has not returned since the repair.",severity:"Medium",confidence:98,first:"Aug 26",last:"Sep 5",count:27,action:"Validated — no recurrence for 8 days",source:"Guardian observed 27 dropouts before the repair and none during 8 days of normal use afterward.",inference:"The repair resolved the original condition with high confidence.",bucket:"Resolved · Verified",responded:true,validated:true}
];

const groupDefs:Record<Major,{label:string;
children:string[]}>= {all:{label:"All",children:[]},detected:{label:"Detected",children:["Actively Happening","Unresolved · Session","Unresolved · Week","Unresolved · Month","Unresolved · Old","Resolved · Unverified","Resolved · Verified"]},user:{label:"User Reported",children:["User Reported · Unresolved","User Reported · Resolved"]},snoozed:{label:"Snoozed",children:["Snoozed · Session","Snoozed · Permanent"]}};

const tone:Record<string,string>={active:"red",unresolved:"amber","resolved-unverified":"slate","resolved-verified":"green","user-open":"blue","user-resolved":"green","snoozed-session":"slate","snoozed-permanent":"slate"};

function ShieldMark({count}: {count?:number}){return <span className="shield-mark">
<Shield size={21} fill="currentColor"/>{count!==undefined&&count>0&&<b>{Math.min(count,9999)}</b>}</span>}
function IssueCard({issue,onOpen}:{issue:Issue;
onOpen:()=>void}){const Icon=issue.icon;
return <button onClick={onOpen} className="issue-card">
<span className={`issue-icon ${tone[issue.state]}`}>
<Icon size={18}/>
</span>
<div>
<div className="issue-title">
<h3>{issue.title}</h3>
<ChevronRight size={17}/>
</div>
<p>{issue.belief}</p>
<div className="card-meta">
<b>{issue.action}</b>
<span>{issue.count} occurrences</span>
<span>Last seen {issue.last}</span>
<span>{issue.confidence}% confidence</span>
</div>
</div>
</button>}
function Section({title,icon:Icon,children,open=true}:{title:string;
icon:typeof Activity;
children:React.ReactNode;
open?:boolean}){return <details className="detail-section" open={open}>
<summary>
<span>
<Icon size={17}/>{title}</span>
<ChevronDown size={16}/>
</summary>
<div className="detail-body">{children}</div>
</details>}
function Fact({label,value}:{label:string;
value:string}){return <div className="fact">
<span>{label}</span>
<b>{value}</b>
</div>}
function TimeItem({time,title,text,bad,good}:{time:string;
title:string;
text:string;
bad?:boolean;
good?:boolean}){return <div className="time-item">
<i className={bad?"bad":good?"good":""}/>
<div>
<small>{time}</small>
<b>{title}</b>
<p>{text}</p>
</div>
</div>}
function Life({label,done,bad}:{label:string;
done?:boolean;
bad?:boolean}){return <div className={`life ${done?"done":""} ${bad?"bad":""}`}>
<span>{bad?<XCircle size={15}/>:done?<Check size={15}/>:<Clock3 size={15}/>}</span>
<b>{label}</b>
</div>}
function ErrorTrendChart(){
 const [duration,setDuration]=useState<"week"|"month">("week");
 const [hover,setHover]=useState<{x:number;y:number;label:string;count:number;kind:string}|null>(null);
 const today=new Date();today.setHours(0,0,0,0);
 const history=Array.from({length:30},(_,i)=>{const date=new Date(today);date.setDate(today.getDate()-(29-i));return {date,unresolved:Math.max(2,5+Math.round(i*.24)+[0,2,-1,1,-2,2,0][i%7]),resolved:Math.max(0,1+Math.round(i*.12)+[0,1,0,2,1,0,1][i%7])}});
 const data=duration==="week"?history.slice(-7):history;
 const width=480,height=178,left=38,right=466,top=20,bottom=140;
 const maxValue=Math.max(...data.flatMap(d=>[d.unresolved,d.resolved]),1);
 const tickStep=Math.max(1,Math.ceil(maxValue/4));
 const ceiling=tickStep*4;
 const yFor=(value:number)=>bottom-(value/ceiling)*(bottom-top);
 const makePoints=(key:"unresolved"|"resolved")=>data.map((d,i)=>({x:left+(i/(data.length-1))*(right-left),y:yFor(d[key]),count:d[key],date:d.date}));
 const unresolved=makePoints("unresolved"),resolved=makePoints("resolved");
 const line=(p:typeof unresolved)=>p.map(x=>`${x.x},${x.y}`).join(" ");
 const area=`M ${unresolved[0].x} ${bottom} L ${line(unresolved).replaceAll(" "," L ")} L ${unresolved.at(-1)?.x} ${bottom} Z`;
 const dateLabel=(d:Date)=>new Intl.DateTimeFormat(undefined,{month:"short",day:"numeric"}).format(d);
 const labelIndexes=duration==="week"?data.map((_,i)=>i):[0,7,14,21,29];
 return <div className="error-chart"><div className="chart-heading"><div><span>Issue outcomes over time</span><small><i className="legend unresolved"/>Unresolved <i className="legend resolved"/>Resolved</small></div><div className="chart-actions"><b>{unresolved.at(-1)?.count} unresolved today</b><select aria-label="Graph duration" value={duration} onChange={e=>{setDuration(e.target.value as "week"|"month");setHover(null)}}><option value="week">Week</option><option value="month">Month</option></select></div></div><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${duration} history of unresolved and resolved issues through ${dateLabel(today)}`} onMouseLeave={()=>setHover(null)}><defs><linearGradient id="errorFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#d64a43" stopOpacity=".25"/><stop offset="1" stopColor="#d64a43" stopOpacity=".02"/></linearGradient></defs><g className="chart-grid">{[0,1,2,3,4].map(i=>{const value=ceiling-i*tickStep,y=yFor(value);return <g key={value}><line x1={left} y1={y} x2={right} y2={y}/><text x={left-7} y={y+3} textAnchor="end">{value}</text></g>})}</g><path className="chart-area" d={area}/><polyline className="chart-line unresolved-line" points={line(unresolved)}/><polyline className="chart-line resolved-line" points={line(resolved)}/><g className="chart-dots unresolved-dots">{unresolved.map(p=><circle key={p.date.toISOString()} cx={p.x} cy={p.y} r="4" onMouseEnter={()=>setHover({x:p.x,y:p.y,label:dateLabel(p.date),count:p.count,kind:"Unresolved"})}/>)}</g><g className="chart-dots resolved-dots">{resolved.map(p=><circle key={p.date.toISOString()} cx={p.x} cy={p.y} r="4" onMouseEnter={()=>setHover({x:p.x,y:p.y,label:dateLabel(p.date),count:p.count,kind:"Resolved"})}/>)}</g><g className="chart-labels">{labelIndexes.map(i=><text key={i} x={(duration==="week"?unresolved:resolved)[i].x} y="158" textAnchor={i===0?"start":i===data.length-1?"end":"middle"}>{i===data.length-1?"Today":dateLabel(data[i].date)}</text>)}</g>{hover&&<g className="chart-tooltip" transform={`translate(${Math.min(hover.x,390)} ${Math.max(hover.y-42,4)})`}><rect width="86" height="34" rx="5"/><text x="7" y="13">{hover.label}</text><text x="7" y="27">{hover.kind}: {hover.count}</text></g>}</svg></div>
}
function Detail({issue}:{issue:Issue}){const Icon=issue.icon;
return <div className="detail-wrap">
<div className="detail-hero">
<span className={`issue-icon ${tone[issue.state]}`}>
<Icon size={20}/>
</span>
<div>
<div className="eyebrow">{issue.userReported?"User-reported issue":"Guardian detected issue"} · GDN-{issue.id.toUpperCase()}-042</div>
<h2>{issue.title}</h2>
</div>
</div>
<div className="pills">
<span className={`pill ${tone[issue.state]}`}>{issue.bucket}</span>
<span className="pill">{issue.severity} importance</span>
<span className="pill">{issue.confidence}% confidence</span>
</div>
<div className="belief-box">
<div className="eyebrow">What Guardian believes</div>
<p>{issue.belief}</p>
</div>
<div className="detail-stack">
 <Section title="Summary" icon={FileCheck2}>
<div className="fact-grid">
<Fact label="First seen" value={issue.first}/>
<Fact label="Last seen" value={issue.last}/>
<Fact label="Occurrences" value={`${issue.count} recorded`}/>
<Fact label="Recommended next step" value={issue.action}/>
</div>
</Section>
 <Section title="Why Guardian thinks this is happening" icon={Fingerprint}>
<div className="stack">
<div className="evidence observed">
<span>Observed</span>
<p>{issue.source}</p>
</div>
<div className="evidence inferred">
<span>Inferred</span>
<p>{issue.inference}</p>
</div>{issue.ambiguous&&<div className="uncertain">
<b>Evidence is incomplete.</b> Guardian is intentionally not choosing a cause yet.</div>}</div>
</Section>
 <Section title="Evidence timeline" icon={History}>
<div className="timeline">
<TimeItem time={issue.last} title="Condition observed again" text={issue.source}/>{issue.failed&&<TimeItem time="Yesterday, 3:18 PM" title="Validation failed" text="The same startup failure returned after the previous repair." bad/>}{issue.validated&&<TimeItem time="8-day observation period" title="Validation succeeded" text="Normal use continued with no recurrence." good/>}<TimeItem time={issue.first} title="Issue created" text="Guardian grouped repeated observations into one durable issue."/>
</div>
<button className="quiet">View all {issue.count} occurrences</button>
</Section>
 <Section title="User comments" icon={MessageSquareText}>{issue.note?<blockquote>“{issue.note}”<footer>— You · saved Sep 3</footer>
</blockquote>:<div className="empty-row">
<p>No comment has been added.</p>
<button>Add context</button>
</div>}</Section>
 <Section title="User disposition" icon={Archive} open={issue.state.includes("snoozed")}>
<p className="copy">Your decisions remain attached to the issue and can be revised later.</p>
<div className="choice-grid">{["Acknowledge","Snooze until reboot","Accept while condition remains","Accept permanently","Reopen if impact changes","Reopen if severity increases"].map(x=>
<button key={x}>{x}</button>)}</div>
</Section>
 <Section title="AI investigation" icon={Sparkles}>
<div className="assistant-card">
<b>
<Bot size={17}/> Investigation brief</b>
<p>I compared timing, recent local changes, and known patterns. The evidence supports checking the smallest reversible cause first. Nothing was submitted externally.</p>
<div>
<button className="primary">Continue investigation</button>
<button className="quiet">Review reasoning</button>
</div>
</div>
</Section>
 {issue.failed&&<Section title="Previous repair attempts" icon={Wrench}>
<div className="validation-banner failed">
<XCircle size={20}/>
<div>
<b>Previous repair did not resolve this issue.</b>
<p>Clearing the application cache appeared to help once, but the same failure recurred 19 hours later.</p>
</div>
</div>
</Section>}
 <Section title="Actual changes made" icon={FileCheck2} open={false}>
<p className="copy">Guardian records what changed—not only what was proposed—so validation can test the real machine state.</p>
<div className="change-row">
<Check size={15}/> One local change recorded;
 original preserved for rollback.</div>
<div className="change-row">
<Check size={15}/> No packages installed. No personal files changed.</div>
</Section>
 <Section title="Validation" icon={ShieldCheck}>
<div className="lifecycle">
<Life label="Observed problem" done/>
<Life label="AI investigation" done/>
<Life label="Proposed repair" done/>
<Life label="Repair attempted" done/>
<Life label="Changes recorded" done/>
<Life label="Observed afterward" done/>
<Life label={issue.failed?"Validation failed":issue.validated?"Validation succeeded":"Validation pending"} done={issue.failed||issue.validated} bad={issue.failed}/>
</div>
</Section>
 {issue.upstream&&<Section title="Known upstream information" icon={Bug}>
<div className="upstream">
<b>Possible match · restic/restic #4873</b>
<p>Same restart signature after interrupted snapshots;
 storage target and release differ.</p>
<small>Not locally validated. Guardian has not submitted information externally.</small>
</div>
</Section>}
 <Section title="Fix capsule / reusable repair knowledge" icon={Zap} open={!!issue.validated}>
<div className="capsule">
<Archive size={18}/>
<div>
<b>{issue.validated?"USB audio stability repair":"Startup recovery procedure"}</b>
<p>Saved knowledge for a future reinstall or similar machine.</p>
</div>
<span>{issue.validated?"Validated · Portable":"Needs review"}</span>
</div>
</Section>
 <Section title="Technical details" icon={Terminal} open={false}>
<div className="fact-grid tech">
<Fact label="Issue fingerprint" value={`guardian:${issue.id}:7c1a9e`}/>
<Fact label="Boot context" value="Current boot · session 4"/>
<Fact label="Evidence retained" value={`${issue.count} normalized events`}/>
<Fact label="Last correlation" value="Local observations only"/>
</div>
</Section>
</div>
</div>}
function ReportDialog({open,onOpenChange}:{open:boolean;
onOpenChange:(v:boolean)=>void}){return <Dialog open={open} onOpenChange={onOpenChange}>
<DialogContent className="modal">
<DialogHeader>
<DialogTitle>Report an issue</DialogTitle>
<p>Tell Guardian what happened. Your report joins the same durable issue ledger as machine-detected conditions.</p>
</DialogHeader>
<div className="form-grid">
<label className="wide">Tie to detected issue <select>
<option>No association</option>
<option>Notes closes just after opening</option>
<option>Wireless connection briefly pauses</option>
</select>
</label>
<label className="wide">Issue description<textarea placeholder="What went wrong?"/>
</label>
<label className="wide">Steps leading to the issue<textarea placeholder="What were you doing before it happened?"/>
</label>
<label>Can it be recreated?<select>
<option>Not sure</option>
<option>Yes</option>
<option>No</option>
</select>
</label>
<label>Related area<select>
<option>Application</option>
<option>Boot-up</option>
<option>System</option>
<option>Hardware</option>
<option>Network</option>
</select>
</label>
<label className="wide">Steps to recreate<textarea placeholder="Optional steps"/>
</label>
<label>When it started<input type="datetime-local"/>
</label>
<label>Last occurrence<input type="datetime-local"/>
</label>
<label>Frequency<select>
<option>Once</option>
<option>Occasionally</option>
<option>Often</option>
<option>Every time</option>
</select>
</label>
</div>
<div className="modal-actions">
<button className="quiet" onClick={()=>onOpenChange(false)}>Cancel</button>
<button className="primary" onClick={()=>onOpenChange(false)}>Add to Guardian</button>
</div>
</DialogContent>
</Dialog>}
function SettingsDialog({open,onOpenChange,visual,onVisualChange}:{open:boolean;
onOpenChange:(v:boolean)=>void;visual:VisualSettings;onVisualChange:(v:VisualSettings)=>void}){const [tab,setTab]=useState("Data"),[browse,setBrowse]=useState(false),[purgeReview,setPurgeReview]=useState(false),[dataSource,setDataSource]=useState<"test"|"live">("test"),[limit,setLimit]=useState("2"),[unit,setUnit]=useState("GB"),[behavior,setBehavior]=useState("overwrite"),[softDeleted,setSoftDeleted]=useState(false),[purgeType,setPurgeType]=useState("ALL"),[purgeRecords,setPurgeRecords]=useState<PurgeRecord[]>([]),[purgeLoading,setPurgeLoading]=useState(false),[purgeError,setPurgeError]=useState("");const localDate=(d:Date)=>{d.setMinutes(d.getMinutes()-d.getTimezoneOffset());return d.toISOString().slice(0,16)};const now=()=>localDate(new Date());const weekAgo=()=>{const d=new Date();d.setDate(d.getDate()-7);return localDate(d)};const [starting,setStarting]=useState(weekAgo),[ending,setEnding]=useState(now);const savePath=dataSource==="test"?"/var/lib/guardian/issues/test":"/var/lib/guardian/issues";
useEffect(()=>{try{const x=localStorage.getItem("guardian.data.settings");if(x){const v=JSON.parse(x);setDataSource(v.dataSource==="live"?"live":"test");setLimit(v.limit||limit);setUnit(v.unit||unit);setBehavior(v.behavior||behavior);setSoftDeleted(!!v.softDeleted)}}catch{}},[]);
useEffect(()=>{localStorage.setItem("guardian.data.settings",JSON.stringify({dataSource,limit,unit,behavior,softDeleted}))},[dataSource,limit,unit,behavior,softDeleted]);
const reviewPurge=async()=>{setPurgeReview(true);setPurgeLoading(true);setPurgeError("");setPurgeRecords([]);try{const params=new URLSearchParams({source:dataSource,type:purgeType,start:new Date(starting).toISOString(),end:new Date(ending).toISOString()});const response=await fetch(`/api/issues?${params}`);const result=await response.json();if(!response.ok)throw new Error(result.error||"Unable to read issue records.");setPurgeRecords(result.records)}catch(error){setPurgeError(error instanceof Error?error.message:"Unable to read issue records.")}finally{setPurgeLoading(false)}};
return <><Dialog open={open} onOpenChange={onOpenChange}>
<DialogContent className="settings-modal">
<DialogHeader>
<DialogTitle>Guardian settings</DialogTitle>
</DialogHeader>
<div className="settings-layout">
<nav>{["Data","Visual","Connections"].map(x=>
<button className={tab===x?"selected":""} onClick={()=>setTab(x)} key={x}>{x}</button>)}</nav>
<section>{tab==="Data"&&<>
<h3>Data</h3>
<div className="setting-row">
<span>
<b>Issue data folder</b>
<small>Test examples are isolated one folder below live records</small>
</span>
<div className="path-control"><input value={savePath} readOnly/><button className="quiet" onClick={()=>setBrowse(true)}><Folder size={15}/>Browse…</button></div>
</div>
<div className="setting-row">
<span><b>Data source</b><small>Live uses the parent of the test folder</small></span>
<select value={dataSource} onChange={e=>setDataSource(e.target.value as "test"|"live")}><option value="test">Test examples</option><option value="live">Live Guardian records</option></select>
</div>
<div className="setting-row">
<span>
<b>Application data size</b>
<small>248 MB currently in use</small>
</span>
<button className="quiet">View storage</button>
</div>
<div className="setting-row">
<span>
<b>Limit size</b>
</span>
<div className="limit-control"><input type="number" min="1" value={limit} onChange={e=>setLimit(e.target.value)}/><select value={unit} onChange={e=>setUnit(e.target.value)}><option>MB</option><option>GB</option></select></div>
</div>
<div className="setting-row">
<span>
<b>Limit behavior</b>
</span>
<select value={behavior} onChange={e=>setBehavior(e.target.value)}>
<option value="overwrite">Write over oldest</option>
<option value="compact">Compact oldest to last unique</option>
</select>
</div>
<h4>Purge repeat errors</h4>
<div className="inline-fields">
<select aria-label="Repeat error types" value={purgeType} onChange={e=>setPurgeType(e.target.value)}>
<option>ALL</option>
<option>Detected</option>
<option>　Actively Happening</option>
<option>　Unresolved</option>
<option>　　Session</option>
<option>　　Week</option>
<option>　　Month</option>
<option>　　Old</option>
<option>　Resolved</option>
<option>　　Unverified</option>
<option>　　Verified</option>
<option>User Reported</option>
<option>　Unresolved</option>
<option>　Resolved</option>
<option>Snoozed</option>
<option>　Session</option>
<option>　Permanent</option>
</select>
<label className="date-field"><span>Starting</span><input type="datetime-local" value={starting} onChange={e=>setStarting(e.target.value)}/></label>
<label className="date-field"><span>Ending</span><input type="datetime-local" value={ending} onChange={e=>setEnding(e.target.value)}/></label>
<button className="quiet" onClick={reviewPurge}>Review purge</button>
</div>
{softDeleted&&<button className="restore-button" onClick={()=>setSoftDeleted(false)}><RotateCcw size={15}/>Restore soft deleted records</button>}
<h4>Export</h4>
<div className="export-grid">{["JSON","CSV","Markdown","SQLite","Settings application format","Settings and history application format"].map(x=>
<button className="quiet" key={x}>{x}</button>)}</div>
</>}{tab==="Visual"&&<>
<h3>Visual</h3>
<div className="setting-row"><span><b>Appearance</b><small>System follows your operating-system preference</small></span><select value={visual.theme} onChange={e=>onVisualChange({...visual,theme:e.target.value as ThemeMode})}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></div>
<div className="setting-row"><span><b>Font</b><small>Applied throughout the Guardian application</small></span><select value={visual.font} onChange={e=>onVisualChange({...visual,font:e.target.value})}><option value="Ubuntu">Ubuntu</option><option value="system-ui">System Default</option><option value="Arial">Arial</option><option value="Verdana">Verdana</option><option value="Tahoma">Tahoma</option><option value="Trebuchet MS">Trebuchet MS</option><option value="Georgia">Georgia</option><option value="Times New Roman">Times New Roman</option><option value="ui-monospace">Monospace</option></select></div>
<div className="setting-row"><span><b>Type</b><small>Increase interface contrast</small></span><select value={visual.contrast?"high":"normal"} onChange={e=>onVisualChange({...visual,contrast:e.target.value==="high"})}><option value="normal">Normal</option><option value="high">High contrast</option></select></div>
<div className="setting-row size-setting"><span><b>Size</b><small>Scale Guardian from 50% to 300%</small></span><div><input aria-label="Application size" type="range" min="50" max="300" step="5" value={visual.scale} onChange={e=>onVisualChange({...visual,scale:Number(e.target.value)})}/><output>{visual.scale}%</output></div></div>
</>}{tab==="Connections"&&<>
<h3>Connections</h3>{["API","MCP","LLM · CloudDirect","LLM · CloudRouter","LLM · Local"].map((x,i)=>
<div className="setting-row" key={x}>
<span>
<b>{x}</b>
<small>{i<2?"Disabled":"Not configured"}</small>
</span>
<button className="quiet">Settings</button>
</div>)}</>}</section>
</div>
</DialogContent>
</Dialog>
<Dialog open={browse} onOpenChange={setBrowse}><DialogContent className="file-browser"><DialogHeader><DialogTitle>Select Guardian data folder</DialogTitle></DialogHeader><div className="browser-location"><button title="Guardian data"><HardDrive size={16}/></button><span>/var/lib/guardian/issues</span></div><div className="browser-body"><nav><button className="selected"><HardDrive size={16}/>Guardian data</button></nav><section><button onDoubleClick={()=>{setDataSource("test");setBrowse(false)}}><Folder size={28}/><span><b>test</b><small>{dataSource==="test"?"Current folder · example records":"Example records"}</small></span></button><button onDoubleClick={()=>{setDataSource("live");setBrowse(false)}}><Folder size={28}/><span><b>issues</b><small>{dataSource==="live"?"Current folder · live records":"Parent folder · live records"}</small></span></button></section></div><div className="browser-actions"><button className="quiet" onClick={()=>setBrowse(false)}>Cancel</button><button className="primary" onClick={()=>setBrowse(false)}>Select</button></div></DialogContent></Dialog>
<Dialog open={purgeReview} onOpenChange={setPurgeReview}><DialogContent className="purge-modal"><DialogHeader><DialogTitle>Review records to purge</DialogTitle><p>Only stored observations matching the selected type and date range are shown. Purging marks them as soft deleted so they can be restored.</p></DialogHeader><div className="purge-source"><Folder size={15}/><span>{savePath}</span></div><div className="purge-range"><span>Starting <b>{starting.replace("T"," ")}</b></span><span>Ending <b>{ending.replace("T"," ")}</b></span></div>{purgeLoading?<div className="purge-empty">Reading issue records…</div>:purgeError?<div className="purge-error">{purgeError}</div>:purgeRecords.length?<div className="purge-table-wrap"><table><thead><tr><th>Record</th><th>Issue</th><th>Observed</th><th>Type</th></tr></thead><tbody>{purgeRecords.map(record=><tr key={record.id}><td>{record.id}</td><td>{record.issue}</td><td>{new Date(record.observedAt).toLocaleString()}</td><td>{record.type}</td></tr>)}</tbody></table></div>:<div className="purge-empty">No stored issue records match this type and date range.</div>}<div className="purge-summary">{purgeRecords.length} {purgeRecords.length===1?"record":"records"} will be soft deleted. No issue or repair history will be permanently erased.</div><div className="browser-actions"><button className="quiet" onClick={()=>setPurgeReview(false)}>Cancel</button><button className="purge-button" disabled={purgeLoading||!!purgeError||purgeRecords.length===0} onClick={()=>{setSoftDeleted(true);setPurgeReview(false)}}><Trash2 size={15}/>Purge {purgeRecords.length} {purgeRecords.length===1?"record":"records"}</button></div></DialogContent></Dialog>
</>}
export default function Home(){const [windowOpen,setWindowOpen]=useState(false),[menuOpen,setMenuOpen]=useState(false),[selected,setSelected]=useState<Issue|null>(null),[major,setMajor]=useState<Major>("all"),[child,setChild]=useState(""),[search,setSearch]=useState(""),[report,setReport]=useState(false),[settings,setSettings]=useState(false),[closePrompt,setClosePrompt]=useState(false),[enabled,setEnabled]=useState(true),[maximized,setMaximized]=useState(false),[position,setPosition]=useState({x:0,y:0}),[responded,setResponded]=useState<string[]>([]),[visual,setVisual]=useState<VisualSettings>({theme:"system",font:"Ubuntu",scale:100,contrast:false}),[systemDark,setSystemDark]=useState(false),[loaded,setLoaded]=useState(false);
const drag=useRef<{x:number;y:number;left:number;top:number}|null>(null);
useEffect(()=>{try{const saved=localStorage.getItem("guardian.visual.settings");if(saved)setVisual({...visual,...JSON.parse(saved)})}catch{}setLoaded(true);const media=window.matchMedia("(prefers-color-scheme: dark)");const update=()=>setSystemDark(media.matches);update();media.addEventListener("change",update);return()=>media.removeEventListener("change",update)},[]);
useEffect(()=>{if(!loaded)return;localStorage.setItem("guardian.visual.settings",JSON.stringify(visual));const dark=visual.theme==="dark"||(visual.theme==="system"&&systemDark);document.documentElement.classList.toggle("guardian-dark",dark);document.documentElement.classList.toggle("guardian-high-contrast",visual.contrast);document.body.style.fontFamily=`${visual.font}, sans-serif`},[visual,systemDark,loaded]);
const unanswered=enabled?issues.filter(i=>!i.responded&&!responded.includes(i.id)).length:0;
const filtered=useMemo(()=>issues.filter(i=>{const group=major==="all"||major==="detected"&&!i.userReported&&!i.state.includes("snoozed")||major==="user"&&!!i.userReported||major==="snoozed"&&i.state.includes("snoozed");
return group&&(!child||i.bucket===child)&&(i.title+" "+i.belief+" "+i.action).toLowerCase().includes(search.toLowerCase())}),[major,child,search]);
const selectMajor=(m:Major)=>{setMajor(m);
setChild("")};
const respond=(id:string)=>setResponded(v=>v.includes(id)?v:[...v,id]);
return <div className="desktop-shell" style={{fontFamily:`${visual.font}, sans-serif`}}>
<div className="ubuntu-topbar">
<div className="activities">Activities</div>
<div className="desktop-clock">Sep 12&nbsp;
&nbsp;
 9:48 PM</div>
<div className="system-area">
<span>EN</span>
<span>◉</span>
<button className={`tray-button ${!enabled?"disabled":""}`} aria-label="Open Guardian" onClick={()=>{setWindowOpen(true);
setMenuOpen(false)}} onContextMenu={e=>{e.preventDefault();
setMenuOpen(v=>!v)}}>
<ShieldMark count={unanswered}/>
</button>
</div>{menuOpen&&<div className="tray-menu">
{!enabled&&<button className="power-menu enable" onClick={()=>setEnabled(true)}><Power size={15}/> Enable Guardian</button>}
<div className="tray-title">
<ShieldMark/>
<span>
<b>Guardian</b>
<small>{enabled?`${unanswered} new issues need a response`:"Detection and sync are turned off"}</small>
</span>
</div>{enabled&&issues.filter(i=>!i.responded&&!responded.includes(i.id)).map(i=>
<div className="tray-issue" key={i.id}>
<button onClick={()=>{setSelected(i);
setWindowOpen(true);
setMenuOpen(false)}}>
<b>{i.title}</b>
<small>{i.last} · {i.severity}</small>
</button>
<div>
<button onClick={()=>respond(i.id)}>Snooze</button>
<button onClick={()=>respond(i.id)}>Acknowledge</button>
</div>
</div>)}{unanswered===0&&<div className="tray-empty">No new issues awaiting a response.</div>}<button className="open-guardian" onClick={()=>{setWindowOpen(true);
setMenuOpen(false)}}>Open Guardian</button>
{enabled&&<button className="power-menu disable" onClick={()=>setEnabled(false)}><Power size={15}/> Disable Guardian</button>}
</div>}</div>
<div className="wallpaper">
<div className="wallpaper-glow"/>
<div className="dock">
<span>●</span>
<span>▣</span>
<span>◫</span>
<span>⌁</span>
<span>▤</span>
</div>
</div>{windowOpen&&<div className={`app-window ${maximized?"maximized":""}`} style={maximized?undefined:{translate:`${position.x}px ${position.y}px`}} onPointerMove={e=>{if(!drag.current||maximized)return;setPosition({x:drag.current.left+e.clientX-drag.current.x,y:drag.current.top+e.clientY-drag.current.y})}} onPointerUp={()=>drag.current=null}>
<header className="window-titlebar" onDoubleClick={()=>setMaximized(v=>!v)} onPointerDown={e=>{if((e.target as HTMLElement).closest("button")||maximized)return;drag.current={x:e.clientX,y:e.clientY,left:position.x,top:position.y};(e.currentTarget.parentElement as HTMLElement)?.setPointerCapture(e.pointerId)}}>
<div className={`window-title ${!enabled?"guardian-disabled":""}`}>
<ShieldMark/>
<span>
<b>Guardian {!enabled&&<em>· Disabled</em>}</b>
<small>{enabled?"Issue center":"Detection and sync are off"}</small>
</span>
</div>
<div className="window-actions">
<button title="Settings" onClick={()=>setSettings(true)}>
<Settings size={18}/>
</button>
<button title="Minimize to top bar" onClick={()=>setWindowOpen(false)}>
<Minus size={18}/>
</button>
<button title={maximized?"Restore window":"Maximize window"} onClick={()=>setMaximized(v=>!v)}>
<Maximize2 size={16}/>
</button>
<button title="Close Guardian" className="close" onClick={()=>setClosePrompt(true)}>
<X size={18}/>
</button>
</div>
</header>
<div className="app-scroll" style={{zoom:visual.scale/100}}>
<main className="app-content">
<section className="critical">
<div className="critical-main">
<div className="eyebrow">Summary · Most critical</div>
<p>Two conditions are active now. Notes startup failures rose from 3 to 9 occurrences;
 the backup restart loop remains the most active unresolved condition.</p>
<button onClick={()=>setSelected(issues[0])}>Review most critical <ChevronRight size={16}/>
</button>
</div>
<ErrorTrendChart/>
</section>
<div className="tabs-toolbar"><div className="group-tabs">{(Object.keys(groupDefs) as Major[]).map(k=>
<button className={major===k?"active":""} onClick={()=>selectMajor(k)} key={k}>
<span>{groupDefs[k].label}</span>
<b>{Math.min(k==="all"?issues.length:k==="detected"?5:k==="user"?1:2,9999)}</b>
</button>)}</div><div className="header-controls">{!enabled&&<button className="enable-button" onClick={()=>setEnabled(true)}><Power size={16}/>Enable</button>}<button className="sync" title={enabled?"Time Since Sync":"Sync unavailable while Guardian is disabled"} disabled={!enabled}><RefreshCw size={17}/><b>{enabled?"00:02":"--:--"}</b></button><button className="report" onClick={()=>setReport(true)}><MessageSquareText size={17}/>Report Issue</button><button className="icon-button" title="Settings" onClick={()=>setSettings(true)}><Settings size={18}/></button></div></div>{major!=="all"&&<div className="subtabs">
<button className={!child?"active":""} onClick={()=>setChild("")}>All {groupDefs[major].label}</button>{groupDefs[major].children.map(x=>
<button className={child===x?"active":""} onClick={()=>setChild(x)} key={x}>{x}<b>{issues.filter(i=>i.bucket===x).length}</b>
</button>)}</div>}<div className="filter-block">
<label>
<Search size={17}/>
<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search issues (contains)"/>
</label>
<div>
<span>From</span>
<input type="datetime-local"/>
<span>To</span>
<input type="datetime-local"/>
</div>
</div>
<div className="issue-list">{filtered.map(i=>
<IssueCard issue={i} key={i.id} onOpen={()=>setSelected(i)}/>)}</div>{filtered.length===0&&<div className="no-results">No issues match these filters.</div>}<footer>
<CircleDot size={14}/> Guardian is observing locally · Synthetic prototype data</footer>
</main>
</div>
</div>}{!windowOpen&&<button className="desktop-hint" onClick={()=>setWindowOpen(true)}>
<ShieldMark count={unanswered}/>
<span>
<b>{enabled?"Guardian is running":"Guardian is disabled"}</b>
<small>{enabled?"Click the shield in the top bar to open":"Open Guardian to enable monitoring"}</small>
</span>
</button>}<Sheet open={!!selected} onOpenChange={o=>!o&&setSelected(null)}>
<SheetContent side="right" className="inspector">
<SheetHeader className="sr-only">
<SheetTitle>Issue detail</SheetTitle>
</SheetHeader>{selected&&<Detail issue={selected}/>}</SheetContent>
</Sheet>
<ReportDialog open={report} onOpenChange={setReport}/>
<SettingsDialog open={settings} onOpenChange={setSettings} visual={visual} onVisualChange={setVisual}/>
<Dialog open={closePrompt} onOpenChange={setClosePrompt}>
<DialogContent className="close-modal">
<DialogHeader><DialogTitle>Close Guardian?</DialogTitle><p>Guardian can keep watching quietly in the top bar, or you can turn off detection and sync.</p></DialogHeader>
<div className="close-options">
<button onClick={()=>{setWindowOpen(false);setClosePrompt(false)}}><Shield size={20}/><span><b>Minimize to top bar</b><small>Guardian keeps watching and recording issues.</small></span></button>
<button className="turn-off" onClick={()=>{setEnabled(false);setWindowOpen(false);setClosePrompt(false)}}><Power size={20}/><span><b>Turn off Guardian</b><small>Stops detection and sync until you enable it again.</small></span></button>
</div>
</DialogContent>
</Dialog>
</div>}
