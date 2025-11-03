document.addEventListener('DOMContentLoaded', ()=>{
  const longInput = document.getElementById('long-url-input');
  const customInput = document.getElementById('custom-short-code-input');
  const ttlSelect = document.getElementById('ttl-select');
  const submitBtn = document.getElementById('submit-button');
  const resultBox = document.getElementById('result-box');
  const shortLink = document.getElementById('short-url-link');
  const copyBtn = document.getElementById('copy-button');
  const errorBox = document.getElementById('error-box');

  const API = '/api/v1/links';

  submitBtn.addEventListener('click', async ()=>{
    errorBox.textContent='';
    let long_url = longInput.value.trim();
    if(!long_url) { errorBox.textContent='Enter URL'; return; }
    if(!/^https?:\/\//.test(long_url)) long_url='https://'+long_url;

    let payload={long_url, ttl:ttlSelect.value};
    let code = customInput.value.trim();
    if(code) payload.custom_code=code;

    submitBtn.disabled=true;
    try{
      let res = await fetch(API,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload)
      });
      let data = await res.json();
      if(res.ok){
        shortLink.href = data.short_url;
        shortLink.textContent = data.short_url;
        resultBox.style.display='block';
      }else{
        errorBox.textContent = data.detail || 'Server error';
      }
    }catch(e){
      errorBox.textContent='Network error';
    }finally{
      submitBtn.disabled=false;
    }
  });

  copyBtn.addEventListener('click', async ()=>{
    try{
      await navigator.clipboard.writeText(shortLink.href);
      copyBtn.textContent='Copied!';
      setTimeout(()=>copyBtn.textContent='Copy',1500);
    }catch(e){
      errorBox.textContent='Copy failed';
    }
  });
});
