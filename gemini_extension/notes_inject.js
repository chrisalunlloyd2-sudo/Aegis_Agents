// AEGIS-DIMON RESEARCH NOTES (Native AppData Inject)
setInterval(function() {
    document.querySelectorAll('.model-response-text, [data-test-id="model-response"]').forEach(res => {
        if (res.querySelector('.aegis-note-btn')) return;
        const btn = document.createElement('button');
        btn.className = 'aegis-note-btn';
        btn.innerText = '📌 Save to RAG';
        btn.style = 'margin-top: 10px; padding: 5px 10px; background: #8B0000; color: white; border: none; border-radius: 5px; cursor: pointer;';
        btn.onclick = () => {
            fetch('http://localhost:5000/api/research/note', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: res.innerText, source: 'Native AppData App' })
            }).then(() => { btn.innerText = '✅ Saved'; btn.style.background = '#065f46'; });
        };
        res.appendChild(btn);
    });
}, 3000);
