function confirmarExclusao(){return window.confirm("Tem certeza que deseja excluir este registro?");}
document.addEventListener("DOMContentLoaded",()=>{document.querySelectorAll(".alert").forEach((alerta)=>{setTimeout(()=>{alerta.style.transition="opacity .3s ease";alerta.style.opacity="0";setTimeout(()=>alerta.remove(),300);},4500);});});
