// 🧠 AEGIS-DIMON: CANADIAN ULTRA NATIVE HACK v3.1
// Purpose: Brute-Force RAG, Research Notes, and DIMON Logic Learning

console.log("🏎️💨 [DIMON] Canadian Ultra Extension v3.1 Active.");

// 1. TIMESCALE DB READ ACCESS (@rag, @learn, @logic triggers)
document.addEventListener('input', async (e) => {
    const target = e.target;
    if (target.tagName === 'TEXTAREA' || target.contentEditable === 'true') {
        const text = target.innerText || target.value;
        
        // --- @rag Trigger (Retrieve Context) ---
        if (text.includes('@rag ')) {
            const query = text.split('@rag ')[1];
            if (query.length > 3 && text.endsWith('??')) { // Trigger on ??
                const cleanQuery = query.replace('??', '').trim();
                console.log("🔍 [RAG] Fetching manifold for:", cleanQuery);
                try {
                    const response = await fetch(`http://localhost:5000/api/neural/search?q=${encodeURIComponent(cleanQuery)}`);
                    const data = await response.json();
                    if (data.results && data.results.length > 0) {
                        const context = `\n\n[CONTEXT FROM TIMESCALE DB]:\n${data.results.map(r => r.content).join('\n')}\n`;
                        if (target.tagName === 'TEXTAREA') target.value = text.replace('@rag ' + query, context);
                        else target.innerText = text.replace('@rag ' + query, context);
                    }
                } catch (err) { console.log("❌ [RAG] Sync offline."); }
            }
        }

        // --- @learn Trigger (Teach Logic) ---
        if (text.includes('@learn ')) {
            const rule = text.split('@learn ')[1];
            if (rule.length > 3 && text.endsWith('!!')) { // Trigger on !!
                const cleanRule = rule.replace('!!', '').trim();
                console.log("🧠 [DIMON-LEARN] Saving rule:", cleanRule);
                fetch('http://localhost:5000/api/logic/learn', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ rule: cleanRule })
                });
                if (target.tagName === 'TEXTAREA') target.value = text.replace('@learn ' + rule, '[DIMON Rule Learned] ');
                else target.innerText = text.replace('@learn ' + rule, '[DIMON Rule Learned] ');
            }
        }

        // --- @logic Trigger (Apply Learned Rules) ---
        if (text.includes('@logic!!')) {
            try {
                const response = await fetch('http://localhost:5000/api/logic/rules');
                const data = await response.json();
                if (data.rules && data.rules.length > 0) {
                    const rulesText = `\n[AEGIS-DIMON LEARNED LOGIC]:\n${data.rules.map(r => "- " + r.content).join('\n')}\nPlease apply this logic to the current session.\n`;
                    if (target.tagName === 'TEXTAREA') target.value = text.replace('@logic!!', rulesText);
                    else target.innerText = text.replace('@logic!!', rulesText);
                }
            } catch (err) {}
        }
    }
});

// 2. RESEARCH NOTES UI
function injectNoteButtons() {
    const responses = document.querySelectorAll('.model-response-text, [data-test-id="model-response"]');
    responses.forEach(res => {
        if (res.querySelector('.aegis-note-btn')) return;
        const btn = document.createElement('button');
        btn.className = 'aegis-note-btn';
        btn.innerText = '📌 Save to RAG';
        btn.style = 'margin-top: 10px; padding: 5px 10px; background: #8B0000; color: white; border: none; border-radius: 5px; cursor: pointer;';
        btn.onclick = () => {
            fetch('http://localhost:5000/api/research/note', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: res.innerText, source: 'AppData App' })
            }).then(() => { btn.innerText = '✅ Saved'; btn.style.background = '#065f46'; });
        };
        res.appendChild(btn);
    });
}
setInterval(injectNoteButtons, 3000);

// 3. CLEANUP (Removing broken CSS)
const oldStyles = document.querySelectorAll('style');
oldStyles.forEach(s => { if (s.textContent.includes('invert')) s.remove(); });
