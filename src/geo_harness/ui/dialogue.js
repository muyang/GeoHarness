'use strict';
// Deliberately small Markdown subset, built only from safe text DOM nodes.
function renderAssistantText(parent,text){
 const lines=String(text).split('\n');
 function inline(el,value){
  const tokens=value.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g);
  for(const token of tokens){if(token.startsWith('`')&&token.endsWith('`')){const n=document.createElement('code');n.textContent=token.slice(1,-1);el.append(n);}else if(token.startsWith('**')&&token.endsWith('**')){const n=document.createElement('b');n.textContent=token.slice(2,-2);el.append(n);}else el.append(document.createTextNode(token));}
 }
 for(let i=0;i<lines.length;i++){
  const line=lines[i];if(!line.trim())continue;
  if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-+:?\s*\|/.test(lines[i+1])){
   const wrap=document.createElement('div');wrap.className='dialogue-table';const table=document.createElement('table');
   const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(v=>v.trim());
   const row=(text,heading)=>{const tr=document.createElement('tr');for(const cell of cells(text)){const td=document.createElement(heading?'th':'td');inline(td,cell);tr.append(td);}table.append(tr);};
   row(line,true);i++;while(i+1<lines.length&&lines[i+1].includes('|'))row(lines[++i],false);wrap.append(table);parent.append(wrap);continue;
  }
  const heading=/^(#{1,4})\s+(.+)$/.exec(line);const list=/^(?:[-*]|\d+\.)\s+(.+)$/.exec(line);
  const el=document.createElement(heading?'h4':'p');if(list)el.className='dialogue-item';inline(el,heading?heading[2]:list?'• '+list[1]:line);parent.append(el);
 }
}
