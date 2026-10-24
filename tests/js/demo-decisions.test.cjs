const test = require('node:test');
const assert = require('node:assert/strict');
const {summarize} = require('../../apps/web/assets/demo-decisions.js');

test('registration and evaluation decisions use current records', () => {
  const registered = summarize(0, {primary:[{name:'knowledge-agent',display_name:'Knowledge',latest_version:'1.0.0',lifecycle_state:'active'}]});
  assert.match(registered.headline, /1 registered/);
  assert.equal(registered.facts[0].value, 'v1.0.0 · active');
  const failed = summarize(1, {primary:[{agent_name:'inventory-agent',gate_passed:false,run_id:'bad',suite_id:'inventory',suite_version:'1.0.0'}],detail:{gate:{reasons:[{passed:false,message:'Safety gate failed'}]}}});
  assert.match(failed.headline, /FAIL/);
  assert.match(failed.facts[2].value, /Safety gate failed/);
  assert.equal(summarize(2, {primary:[]}).observed, false);
});

test('policy, runtime and canary records do not become invented proof', () => {
  assert.equal(summarize(3, {primary:[{target:'admin.delete',allowed:false,outcome:'deny',reasons:['undeclared_tool']}]}).observed, true);
  assert.equal(summarize(3, {primary:[]}).observed, false);
  assert.equal(summarize(4, {primary:{agents:[{agent_name:'knowledge-agent',request_count:0}]}}).observed, false);
  assert.match(summarize(7, {primary:{agents:[{agent_name:'knowledge-agent',request_count:2,availability:1,p95_latency_ms:25.5,last_trace_id:'abc'}]}}).facts[1].value, /25.5 ms/);
  const overview={routes:[{id:'route',agent_name:'knowledge-agent',environment:'production',revision:2,allocation:{candidate_weight_basis_points:500}}],canaries:[{route_id:'route',progress:{state:'5_percent'},latest_gate:{allowed:true,checks:[{passed:true},{passed:false,name:'latency'}]}}]};
  assert.match(summarize(5, {primary:overview}).facts[2].value, /latency/);
  assert.match(summarize(6, {primary:overview}).headline, /5%/);
  assert.match(summarize(6, {primary:{...overview,routes:[{...overview.routes[0],allocation:{candidate_weight_basis_points:0}}]}}).note, /rollback/);
});

test('incident, rollback and recovery remain distinct decisions', () => {
  const incident={id:'incident',agent_name:'knowledge-agent',detected_at:'2026-01-01',severity:'critical',status:'verifying'};
  const detected=summarize(8, {primary:[incident],triggers:[{observed_value:700,threshold:442.5}],evidence:[{kind:'config_diff',attributes:{changes:{'spec.retrieval.top_k':{before:5,after:50}}}}]});
  assert.equal(detected.facts[2].value, '5 → 50');
  const investigation={incident,analysis:{probable_cause:{statement:'Retrieval fan-out',citations:[{source_ref:'fault://x'}]},missing_evidence:[]},rollbacks:[{status:'executed',target_release_id:'stable'}]};
  assert.equal(summarize(9, {primary:[incident],investigation}).facts[1].value, '1');
  const overview={routes:[{agent_name:'knowledge-agent',environment:'production',allocation:{candidate_weight_basis_points:0}}]};
  assert.match(summarize(10, {primary:overview,investigation}).note, /still needs/);
  assert.match(summarize(11, {primary:[incident],investigation}).note, /not recovery/);
  assert.equal(summarize(11, {primary:[],investigation:null}).observed, false);
});
