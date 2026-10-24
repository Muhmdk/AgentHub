(() => {
  const steps = [
    {title:'Register an exact version', text:'Start with three retail agents. Their manifests identify the version, owner, tools, and configuration. An existing version cannot silently acquire different content.', route:'/registry', endpoint:'/registry/agents', proof:'3 agents · Inventory / Knowledge / Shopping\nVersion 1.0.0 · immutable manifest identity'},
    {title:'Block a bad candidate', text:'The seeded Inventory candidate fails required quality and safety gates. On the Evaluations screen, choose its FAIL run and compare it with the Inventory PASS baseline.', route:'/evaluations', endpoint:'/evaluations/runs', proof:'Known-bad Inventory fixture → FAIL\nRequired gate failure → promotion blocked'},
    {title:'Inspect a passing baseline', text:'A passing result records the versioned inputs used to evaluate the agent. Passing offline tests is necessary, but release controls still apply.', route:'/evaluations', endpoint:'/evaluations/runs', proof:'Inventory baseline fixture → PASS\nEvaluation evidence remains linked to its version'},
    {title:'Deny an unauthorized tool', text:'The Knowledge Agent attempts admin.delete. The policy engine checks declared permissions outside the model and records a denial. Open Governance and filter to Deny.', route:'/governance', endpoint:'/governance/audit?outcome=deny&limit=20', proof:'Tool: admin.delete\nDecision: DENY · undeclared tool\nNo administrative action executed'},
    {title:'Send a governed request', text:'Run the request command below in a terminal to exercise your local gateway. The identity header is for local development. OpenAPI exposes the complete request contract.', route:'/docs', endpoint:'/observability/fleet', proof:'Caller → gateway → policy → agent → cited answer', command:true},
    {title:'Inspect the paired-evidence gate', text:'The seeded canary has a saved gate decision based on synthetic paired observations. Shadow execution keeps the stable answer visible while a candidate is compared. This screen shows the gate decision, not production user traffic.', route:'/delivery', endpoint:'/delivery/overview', proof:'Stable answer remains user-visible\nCandidate comparison is isolated\nSeeded paired observations: synthetic'},
    {title:'Limit candidate exposure', text:'The seeded Knowledge route assigns five percent of traffic to a candidate. Inspect the route and guardrails in Delivery. If you already rolled back, the current local state may correctly show zero percent.', route:'/delivery', endpoint:'/delivery/overview', proof:'Illustrative starting allocation\nStable 95% / candidate 5%\nPromotion requires samples, windows, telemetry and guardrails'},
    {title:'Observe the running system', text:'Measurements are recorded by the current API process. Empty values mean no observations. Send an agent request first, then inspect request counts and trace links; a restart clears in-process measurements.', route:'/observability', endpoint:'/observability/fleet', proof:'Illustrative request completed\nLatency recorded → trace linked\nThese preview values are not measurements'},
    {title:'Detect the retrieval regression', text:'The seeded incident changes retrieval top_k from 5 to 50. Its evidence shows increased retrieval p95 while model p95 remains stable. This scenario is an injected fixture.', route:'/incidents-console', endpoint:'/incidents', proof:'Injected configuration change: top_k 5 → 50\nRetrieval latency increases\nModel latency remains stable'},
    {title:'Investigate with citations', text:'Open the incident to inspect its timeline, evidence, and findings. The analyzer cites immutable records and does not have infrastructure credentials. It identifies a likely cause rather than granting itself authority to act.', route:'/incidents-console', endpoint:'/incidents', investigation:true, proof:'Finding: retrieval configuration is the likely cause\nSupporting evidence: configuration + retrieval + model timings'},
    {title:'Request a checked rollback', text:'In the Incidents console, select “Request policy-checked known-good rollback.” This changes the local route. The server derives eligibility and the target from persisted state. Return here and refresh evidence afterward.', route:'/incidents-console', endpoint:'/delivery/overview', proof:'Simulated rollback intent → eligibility checked\nKnown-good target restored\nCandidate traffic → 0%'},
    {title:'Verify recovery', text:'Execution and recovery are different states. A rollback click does not generate a recovery window. Inspect the incident’s current result; the isolated E2E lifecycle test supplies post-rollback observations to exercise recovered status.', route:'/incidents-console', endpoint:'/incidents', investigation:true, proof:'Requested → executed → verifying\nRecovery requires sufficient healthy observations\nThe live console may correctly remain in verification'}
  ];
  const el = id => document.getElementById(id);
  let index = 0, generation = 0;
  const mode = el('demo-mode');
  const publicPreview = document.body.dataset.static === 'true';
  if (publicPreview) {
    mode.querySelector('[value="live"]').remove();
    mode.closest('.demo-toolbar').hidden = true;
  } else if (new URLSearchParams(location.search).get('mode') === 'live') mode.value = 'live';
  const events = [];
  const safeJSON = value => JSON.stringify(value, null, 2);
  const summarize = window.AgentHubDemoDecisions.summarize;
  function record(text) { events.unshift(text); const list = el('demo-events'); list.replaceChildren(); events.slice(0,12).forEach(value => {const li = document.createElement('li'); li.textContent = value; list.append(li);}); }
  function render() {
    generation++;
    const step = steps[index], live = mode.value === 'live';
    el('mode-notice').textContent = live ? 'Local API walkthrough · “Inspect evidence” reads this server. Consequential actions remain in the operator console. Restarting this walkthrough does not reset your database.' : 'Interactive example using sample records. No API requests or changes to a running service happen here.';
    el('stage-count').textContent = `${String(index+1).padStart(2,'0')} / ${steps.length} · ${live ? 'Local API' : 'Simulation'}`;
    el('stage-title').textContent = step.title; el('stage-description').textContent = step.text;
    el('stage-console').href = live ? step.route : (publicPreview ? '../try-locally/' : '/try-locally');
    el('stage-console').textContent = live ? 'Open operator screen ↗' : 'Run the real system →';
    el('stage-action').disabled = false; el('stage-action').textContent = live ? 'Inspect current evidence' : 'Show illustrative outcome';
    el('stage-status').textContent = ''; el('stage-raw').textContent = 'Inspect this stage to see its record.';
    el('stage-evidence').replaceChildren();
    if (step.command) {
      const pre = document.createElement('pre'); pre.className = 'evidence-chip';
      pre.textContent = `curl -sS http://127.0.0.1:8000/gateway/agents/knowledge-agent/invoke \\\n  -H 'Content-Type: application/json' \\\n  -H 'X-AgentHub-Identity: local/demo' \\\n  -d '{"query":"Can I return an unopened product after 20 days?","seed":4}'`;
      el('stage-evidence').append(pre);
    }
    const nav = el('demo-steps'); nav.replaceChildren();
    steps.forEach((s,i) => {const button=document.createElement('button'); button.type='button'; button.textContent=`${String(i+1).padStart(2,'0')}  ${s.title}`; if(i===index) button.setAttribute('aria-current','step'); button.addEventListener('click',()=>{index=i;render();});nav.append(button);});
    el('demo-prev').disabled=index===0;el('demo-next').disabled=index===steps.length-1;
  }
  async function read(path) {
    const response = await fetch(path, {signal:AbortSignal.timeout(10000), headers:{Accept:'application/json'}});
    if (!response.ok) throw new Error(`API returned ${response.status}. Check the local service and access configuration.`);
    return response.json();
  }
  async function liveEvidence(stage) {
    const primary = await read(steps[stage].endpoint);
    const bundle = {primary};
    if(stage===1 || stage===2) {
      const matching = Array.isArray(primary) && primary.find(item => item.agent_name==='inventory-agent' && item.gate_passed===(stage===2));
      if(matching) bundle.detail = await read(`/evaluations/runs/${encodeURIComponent(matching.run_id)}`);
    }
    if(stage>=8) {
      const incidents = stage===10 ? await read('/incidents') : primary;
      const selected = Array.isArray(incidents) && incidents.filter(item=>item.agent_name==='knowledge-agent').sort((a,b)=>String(b.detected_at).localeCompare(String(a.detected_at)))[0];
      if(selected) {
        const path = `/incidents/${encodeURIComponent(selected.id)}`;
        if(stage===8) [bundle.triggers,bundle.evidence] = await Promise.all([read(`${path}/triggers`),read(`${path}/evidence`)]);
        else bundle.investigation = await read(`${path}/investigation`);
      }
    }
    return bundle;
  }
  function showDecision(decision) {
    const card=document.createElement('article'); card.className=`demo-decision ${decision.observed?'observed':'unobserved'}`;
    const heading=document.createElement('h3'); heading.textContent=decision.headline; card.append(heading);
    if(decision.facts.length) {
      const details=document.createElement('dl');
      decision.facts.forEach(item=>{const term=document.createElement('dt');term.textContent=item.label;const value=document.createElement('dd');value.textContent=item.value;details.append(term,value);});
      card.append(details);
    }
    const note=document.createElement('p');note.textContent=decision.note;card.append(note);
    el('stage-evidence').replaceChildren(card);
  }
  el('stage-action').addEventListener('click', async () => {
    const step=steps[index], token=generation;
    if(mode.value==='preview') {
      const proof=document.createElement('p');proof.className='evidence-chip';proof.textContent=step.proof;el('stage-evidence').replaceChildren(proof);
      el('stage-raw').textContent=safeJSON({mode:'browser simulation',stage:index+1,illustration:step.proof.split('\n')});
      el('stage-status').textContent='Illustrative outcome displayed. No API request was sent.';record(`Simulation · ${step.title}`);return;
    }
    el('stage-action').disabled=true;el('stage-status').textContent='Reading current API evidence…';
    try {
      const data=await liveEvidence(index);
      if(token!==generation)return;
      el('stage-raw').textContent=safeJSON(data);
      const decision=summarize(index,data);
      showDecision(decision);
      el('stage-status').textContent=`Current API records read from ${step.endpoint}. ${decision.observed?'A matching record was found.':'The expected proof was not found.'}`;
      record(`Local check · ${step.title} · ${decision.observed?'observed':'not observed'}`);
    } catch(error) {if(token===generation)el('stage-status').textContent=`Evidence unavailable. ${error.message} Use browser simulation or follow Run locally.`;}
    finally {if(token===generation)el('stage-action').disabled=false;}
  });
  el('demo-prev').addEventListener('click',()=>{if(index>0){index--;render();}});
  el('demo-next').addEventListener('click',()=>{if(index<steps.length-1){index++;render();}});
  el('demo-reset').addEventListener('click',()=>{index=0;events.length=0;el('demo-events').replaceChildren();render();});
  mode.addEventListener('change',()=>{events.length=0;el('demo-events').replaceChildren();render();});render();
})();
