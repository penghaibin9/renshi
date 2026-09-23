/* Canonical HR shell only: no legacy Horilla menus, requests or storage. */
(function(){
  'use strict';
  const sidebar=document.getElementById('sidebar');
  const toggle=document.querySelector('[data-hr-sidebar-toggle]');
  const backdrop=document.querySelector('[data-hr-sidebar-backdrop]');
  function setOpen(open){
    if(!sidebar)return;
    sidebar.classList.toggle('sidebar-pinned',Boolean(open));
    if(toggle)toggle.setAttribute('aria-expanded',open?'true':'false');
    if(backdrop)backdrop.hidden=!open;
  }
  if(toggle)toggle.addEventListener('click',()=>setOpen(!sidebar.classList.contains('sidebar-pinned')));
  if(backdrop)backdrop.addEventListener('click',()=>setOpen(false));
  document.addEventListener('keydown',e=>{if(e.key==='Escape')setOpen(false);});
  document.addEventListener('click',e=>{
    if(innerWidth<=767&&e.target.closest('#sidebar a[href]'))setOpen(false);
    document.querySelectorAll('.hr-clean-account[open]').forEach(d=>{if(!d.contains(e.target))d.removeAttribute('open');});
  });
})();
