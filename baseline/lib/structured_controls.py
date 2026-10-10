"""Options-first structured controls; JSON is an explicitly enabled override."""
import html
import json


def render(name, value):
    escaped_name = html.escape(name, quote=True)
    encoded = html.escape(json.dumps(value, ensure_ascii=False), quote=True)
    return (f'<input type="hidden" name="{escaped_name}" value="{encoded}" '
            'data-structured-editor>'
            '<details><summary>Advanced JSON override</summary>'
            '<p>Use only if you understand this configuration.</p>'
            '<label><input type="checkbox" data-json-enable> Enable JSON override</label>'
            f'<textarea data-json-override disabled>{encoded}</textarea></details>'
            '<noscript>Enable JavaScript to edit these choices.</noscript>')


def script():
    return '''<style>
.structured-controls fieldset{border:1px solid #33364a;border-radius:6px;margin:.6rem 0;padding:.8rem;min-width:0}
.structured-controls label{display:flex;flex-wrap:wrap;gap:.6rem;margin:.5rem 0;align-items:center}
.structured-controls input,.structured-controls select{max-width:100%;padding:.4rem}
.structured-controls button{margin:.3rem}.structured-controls legend{font-weight:600}
details{margin:.7rem 0}details textarea{width:100%;box-sizing:border-box;min-height:8rem}
</style><script>
window.BaselineStructuredEditor = class {
 constructor(source, options={}) {
  this.source=source; this.options=options; this.value=null;
  this.view=document.createElement('div');this.view.className='structured-controls';
  this.details=source.parentElement.tagName==='DETAILS'?source.parentElement:
    source.nextElementSibling?.tagName==='DETAILS'?source.nextElementSibling:null;
  if(!this.details){
   this.details=document.createElement('details');
   const summary=document.createElement('summary');summary.textContent='Advanced JSON override';
   this.details.append(summary);source.before(this.details);this.details.append(source);
  }
  this.details.before(this.view);
  this.raw=source.tagName==='TEXTAREA'?source:this.details.querySelector('[data-json-override]');
  this.enable=this.details.querySelector('[data-json-enable]');
  if(!this.enable){
   const label=document.createElement('label');this.enable=document.createElement('input');
   this.enable.type='checkbox';label.append(this.enable,document.createTextNode(' Enable JSON override (advanced)'));
   this.raw.before(label);
  }
  this.raw.disabled=true;
  this.enable.addEventListener('change',()=>{
   this.raw.disabled=!this.enable.checked;this.view.hidden=this.enable.checked;
   this.raw.setCustomValidity('');if(!this.enable.checked)this.set(this.value);
  });
  this.raw.addEventListener('input',()=>{
   if(!this.enable.checked)return;
   try{this.value=JSON.parse(this.raw.value);this.raw.setCustomValidity('');
       if(this.raw!==this.source)this.source.value=this.raw.value;
   }catch(error){this.raw.setCustomValidity('Invalid JSON: '+error.message);}
  });
  if(source.value){try{this.set(JSON.parse(source.value));}catch(error){this.view.textContent='Import a valid configuration or choose a template.';}}
  else this.view.textContent='Discover choices or select a template to start.';
 }
 get(){if(this.enable.checked){this.value=JSON.parse(this.raw.value);}return this.value;}
 set(value){
  this.value=structuredClone(value);this.source.value=JSON.stringify(value,null,2);
  this.raw.value=this.source.value;this.view.replaceChildren();
  this.draw(this.view,this.value,[],v=>{this.value=v;},'Configuration');
 }
 sync(){this.source.value=JSON.stringify(this.value,null,2);this.raw.value=this.source.value;
        this.source.dispatchEvent(new Event('input',{bubbles:true}));}
 choices(path){
  const key=path.filter(x=>typeof x==='string').at(-1);
  return this.options[path.join('.')]||this.options[key]||({
   variant:['desktop','server'],locale:['en_US.UTF-8','en_GB.UTF-8','C.UTF-8'],
   smartd_auto_offline:['on','off'],smartd_attribute_autosave:['on','off'],
   ethtool_autoneg:['on','off'],ethtool_duplex:['full','half'],
   install:['automatic'],self_test_type:['short','long'],
   os:['ubuntu-24.04'],apps:['vscode','spotify','chrome','chatgpt','claude']
  })[key];
 }
 draw(parent,value,path,assign,title){
  if(value!==null && typeof value==='object'){
   const box=document.createElement('fieldset'),legend=document.createElement('legend');
   legend.textContent=title;box.append(legend);parent.append(box);
   if(Array.isArray(value)){
    if(!value.length){const empty=document.createElement('p');empty.textContent='No items selected';box.append(empty);}
    value.forEach((item,index)=>{
     const row=document.createElement('div');box.append(row);
     this.draw(row,item,[...path,index],v=>{value[index]=v;},'Item '+(index+1));
     const remove=document.createElement('button');remove.type='button';remove.textContent='Remove item';
     remove.onclick=()=>{value.splice(index,1);this.sync();this.set(this.value);};row.append(remove);
    });
    const add=document.createElement('button');add.type='button';add.textContent='Add item';
    add.onclick=()=>{const choices=this.choices(path);const sample=value[0];
      value.push(choices?choices.find(v=>!value.includes(v))??choices[0]:
       sample===undefined?'':typeof sample==='object'?structuredClone(sample):typeof sample==='number'?0:typeof sample==='boolean'?false:'');
      this.sync();this.set(this.value);};box.append(add);
   }else{
    for(const [key,item] of Object.entries(value))this.draw(box,item,[...path,key],v=>{value[key]=v;},key.replaceAll('_',' '));
   }
   return;
  }
  const label=document.createElement('label');label.append(document.createTextNode(title));
  let input;const choices=this.choices(path);
  if(choices){input=document.createElement('select');
   const values=[...choices];if(!values.includes(value))values.unshift(value);
   for(const optionValue of values){const option=document.createElement('option');
    option.value=optionValue===null?'':String(optionValue);option.textContent=optionValue===null?'Choose an option':String(optionValue);
    option.selected=optionValue===value;input.append(option);}
  }else{input=document.createElement('input');input.type=typeof value==='boolean'?'checkbox':typeof value==='number'?'number':'text';
   if(typeof value==='boolean')input.checked=value;else input.value=value===null?'':value;
   if(typeof value==='number')input.step=Number.isInteger(value)?'1':'any';}
  input.setAttribute('aria-label',title);
  input.addEventListener('change',()=>{const next=typeof value==='boolean'?input.checked:
    typeof value==='number'?Number(input.value):value===null&&input.value===''?null:input.value;
    if(typeof next==='number'&&!Number.isFinite(next)){input.setCustomValidity('Enter a valid number');return;}
    input.setCustomValidity('');assign(next);this.sync();});
  label.append(input);parent.append(label);
 }
};
for(const source of document.querySelectorAll('[data-structured-editor]')){
 const editor=new BaselineStructuredEditor(source);source.baselineEditor=editor;
}
for(const form of document.querySelectorAll('form[data-autosave]')){
 let timer=null,running=false,pending=false;
 const status=form.querySelector('[data-save-status]');
 function values(){
  const data=new FormData(form),result={};
  for(const [key,type] of data.entries()){
   if(!key.endsWith('__type'))continue;
   const name=key.slice(0,-6),raw=data.get(name);
   if(type==='bool')result[name]=data.has(name);
   else if(raw!==null){
    if(type==='json')result[name]=JSON.parse(raw);
    else if(type==='int'||type==='float'){
     if(raw.trim()==='')throw Error('Enter a number');
     const number=Number(raw);if(!Number.isFinite(number)||(type==='int'&&!Number.isInteger(number)))throw Error('Enter a valid number');
     result[name]=number;
    }else result[name]=raw;
   }
  }
  return result;
 }
 async function save(){
  if(running){pending=true;return;}
  if(!form.reportValidity())return;
  let body;try{body=values();}catch(error){status.textContent='Not saved: '+error.message;return;}
  running=true;status.textContent='Saving…';
  try{
   const response=await fetch(form.action,{method:'POST',credentials:'same-origin',referrerPolicy:'same-origin',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   if(!(response.headers.get('Content-Type')||'').includes('application/json'))throw Error('Session expired or server unavailable; log in again');
   const result=await response.json();
   if(!response.ok||result.outcome!=='applied')throw Error(result.detail||result.error||result.reason||'Change refused');
   status.textContent=result.detail||'Saved';
  }catch(error){status.textContent='Not saved: '+error.message;}
  finally{running=false;if(pending){pending=false;save();}}
 }
 function changed(event){
  if(event.target.matches('[data-json-enable]'))return;
  clearTimeout(timer);status.textContent='Unsaved change';timer=setTimeout(save,400);
 }
 form.addEventListener('change',changed);
 form.addEventListener('input',event=>{if(event.target.type==='hidden')changed(event);});
 form.addEventListener('submit',event=>{event.preventDefault();clearTimeout(timer);save();});
}
</script>'''
