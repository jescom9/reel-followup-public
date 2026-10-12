// Light is the default. Only an explicit choice in this browser enables dark.
(()=>{let theme='light';try{if(localStorage.getItem('reel-theme')==='dark')theme='dark';}catch{}document.documentElement.dataset.theme=theme;document.documentElement.style.colorScheme=theme;})();
