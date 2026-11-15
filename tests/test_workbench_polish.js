/** Secondary actions move into accessible menus without recreating task controls. */
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../ucagent/interfaces/server/static/share/workbench-polish.js'),'utf8');
/** Minimal movable DOM nodes retaining original handler identity and hidden state. */
class Element{
 constructor(){this.children=[];this.events={};this.className='';this.hidden=false;this.open=false;this.attrs={};this.classList={add:k=>this.className+=' '+k};}
 append(...nodes){for(const node of nodes){if(node.parentElement)node.parentElement.children=node.parentElement.children.filter(n=>n!==node);node.parentElement=this;this.children.push(node);}}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(k,fn){this.events[k]=fn;}
 querySelector(s){return this.children.find(n=>s==='summary'?n.tag==='summary':n.className===s.slice(1))||null;}
 contains(n){return n===this||this.children.some(c=>c.contains(n));}
 focus(){this.focused=true;}
}
/** Mount the polish adapter around the existing control nodes. */
function fixture(){const nodes=new Map();for(const s of ['#workbench-content-tabs','#workbench-file-actions','#workbench-report-files','#quote-comment-history','#console-controls','#console-bar','#console-autoscroll-btn','#formal-compare-button','.quote-comment-tip'])nodes.set(s,new Element());const clear=new Element();clear.className='cdanger';nodes.get('#console-controls').append(clear);const created=[],events={};const context=vm.createContext({document:{body:new Element(),querySelector:s=>nodes.get(s),querySelectorAll:()=>created.filter(n=>n.className==='workbench-menu'&&n.open),createElement:tag=>{const n=new Element();n.tag=tag;created.push(n);return n;},addEventListener:(n,f)=>events[n]=f}});vm.runInContext(source,context);return {nodes,created,events,clear};}
test('Report and Output secondary controls retain their original elements and callbacks',()=>{const {nodes,created,clear}=fixture();const report=created.find(n=>n.id==='workbench-report-menu'),output=created.find(n=>n.id==='workbench-output-menu');assert(report.contains(nodes.get('#workbench-file-actions')));assert(report.contains(nodes.get('#quote-comment-history')));assert(report.contains(nodes.get('#formal-compare-button')));assert(output.contains(clear));assert(output.contains(nodes.get('#console-autoscroll-btn')));assert.equal(nodes.get('#workbench-file-actions').parentElement,report.querySelector('.workbench-menu-items'));});
test('Only one menu remains open; Escape closes and returns keyboard focus',()=>{const {created,events}=fixture();const [report,output]=created.filter(n=>n.className==='workbench-menu');report.open=true;output.open=true;output.events.toggle();assert(!report.open);assert(output.open);events.keydown({key:'Escape'});assert(!output.open);assert(output.querySelector('summary').focused);});
test('Pointer outside closes menus without clearing report content or input',()=>{const {created,events}=fixture();const menu=created.find(n=>n.className==='workbench-menu');menu.open=true;events.pointerdown({target:new Element()});assert(!menu.open);assert(!/replaceChildren|innerHTML|apiFetch|sendRuntimeCmd/.test(source));});
