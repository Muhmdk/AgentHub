/* Read-only interpretations of the current API state. Never infer success from a 200 alone. */
(function (root) {
  const list = value => Array.isArray(value) ? value : [];
  const finding = (headline, facts, note, observed = true) => ({headline, facts, note, observed});
  const fact = (label, value) => ({label, value: String(value)});
  const knowledgeRoute = overview => list(overview?.routes).find(route => route.agent_name === 'knowledge-agent' && route.environment === 'production');
  const knowledgeCanary = overview => {
    const route = knowledgeRoute(overview);
    return list(overview?.canaries).find(canary => canary.route_id === route?.id);
  };
  const incident = records => list(records).filter(item => item.agent_name === 'knowledge-agent').sort((a, b) => String(b.detected_at).localeCompare(String(a.detected_at)))[0];
  const percent = basisPoints => `${(Number(basisPoints) / 100).toFixed(0)}%`;

  function summarize(stage, bundle) {
    const records = bundle.primary;
    if (stage === 0) {
      const agents = list(records);
      return agents.length ? finding(`${agents.length} registered agents found`, agents.map(item => fact(item.display_name || item.name, `v${item.latest_version} · ${item.lifecycle_state}`)), 'These records identify saved versions. They do not alone prove an evaluation passed.') : finding('No registered agents found', [], 'Run make demo to seed the local scenario.', false);
    }
    if (stage === 1 || stage === 2) {
      const wantPass = stage === 2;
      const run = list(records).find(item => item.agent_name === 'inventory-agent' && item.gate_passed === wantPass);
      if (!run) return finding(`No ${wantPass ? 'passing' : 'failing'} Inventory evaluation found`, [], 'Seed the scenario, then inspect the Evaluations screen.', false);
      const reasons = list(bundle.detail?.gate?.reasons).filter(item => item.passed === false).map(item => item.message);
      return finding(`Inventory gate: ${run.gate_passed ? 'PASS' : 'FAIL'}`, [fact('Run', run.run_id), fact('Suite', `${run.suite_id} v${run.suite_version}`), fact('Required failures', reasons.length ? reasons.join(' · ') : 'None in this run')], wantPass ? 'A pass is one prerequisite; it does not release an agent by itself.' : 'A failed required gate blocks this candidate from promotion.');
    }
    if (stage === 3) {
      const denied = list(records).find(item => item.target === 'admin.delete' && item.allowed === false);
      return denied ? finding('Unauthorized tool was denied', [fact('Tool', denied.target), fact('Decision', denied.outcome), fact('Reasons', list(denied.reasons).join(' · '))], 'This is a saved policy decision, not a claim that the tool ran.') : finding('No admin.delete denial found', [fact('Other denials', list(records).length)], 'The seeded denial is missing. Check Governance or reset the local demo.', false);
    }
    if (stage === 4 || stage === 7) {
      const agent = list(records?.agents).find(item => item.agent_name === 'knowledge-agent');
      if (!agent || agent.request_count === 0) return finding('No Knowledge requests measured in this API process', [], 'Run the command shown above, then inspect again. Process-local measurements reset on restart.', false);
      return finding(`${agent.request_count} Knowledge request${agent.request_count === 1 ? '' : 's'} measured`, [fact('Availability', agent.availability == null ? 'Not measured' : `${(agent.availability * 100).toFixed(1)}%`), fact('p95 latency', agent.p95_latency_ms == null ? 'Not measured' : `${agent.p95_latency_ms.toFixed(1)} ms`), fact('Last trace', agent.last_trace_id || 'Not available')], 'These are current process observations. Use the trace and gateway response to inspect an individual request.');
    }
    if (stage === 5) {
      const canary = knowledgeCanary(records);
      if (!canary?.latest_gate) return finding('No saved canary gate decision found', [], 'The overview alone cannot prove a shadow comparison happened.', false);
      const gate = canary.latest_gate;
      return finding(`Saved canary gate: ${gate.allowed ? 'ALLOWED' : 'BLOCKED'}`, [fact('Current stage', canary.progress.state), fact('Checks', `${list(gate.checks).filter(check => check.passed).length}/${list(gate.checks).length} passed`), fact('Failed checks', list(gate.checks).filter(check => !check.passed).map(check => check.name).join(' · ') || 'None')], 'This is the persisted decision for synthetic paired evidence, not live production traffic.');
    }
    if (stage === 6) {
      const route = knowledgeRoute(records);
      if (!route) return finding('No Knowledge production route found', [], 'Seed the scenario, then inspect Delivery.', false);
      const weight = route.allocation?.candidate_weight_basis_points ?? 0;
      return finding(`Candidate traffic: ${percent(weight)}`, [fact('Stable traffic', percent(10000 - weight)), fact('Route revision', route.revision), fact('Canary stage', knowledgeCanary(records)?.progress?.state || 'No canary')], weight === 0 ? 'Zero candidate traffic may mean a rollback already happened. Check the incident operation.' : 'This allocation is current route state, not proof of real user traffic.');
    }
    if (stage === 8) {
      const item = incident(records);
      if (!item) return finding('No Knowledge incident found', [], 'Seed the regression scenario, then inspect Incidents.', false);
      const trigger = list(bundle.triggers)[0];
      const config = list(bundle.evidence).find(e => e.kind === 'config_diff');
      const change = config?.attributes?.changes?.['spec.retrieval.top_k'];
      return finding(`Incident: ${item.status}`, [fact('Severity', item.severity), fact('Trigger', trigger ? `${trigger.observed_value} ms vs ${trigger.threshold} ms limit` : 'Not available'), fact('Retrieval top_k', change ? `${change.before} → ${change.after}` : 'Config evidence not available')], 'These are injected local records. Open the incident screen for full source-linked evidence.');
    }
    if (stage === 9) {
      const view = bundle.investigation;
      if (!view) return finding('No investigation found', [], 'Seed the incident before inspecting its analysis.', false);
      const cause = view.analysis?.probable_cause;
      return cause ? finding('Source-cited cause available', [fact('Finding', cause.statement), fact('Citations', list(cause.citations).length), fact('Missing evidence kinds', list(view.analysis?.missing_evidence).join(' · ') || 'None listed')], 'This is a deterministic, evidence-bound finding. It does not authorize a rollback.') : finding('No probable cause established', [fact('Incident state', view.incident?.status || 'Unknown')], 'Review the timeline and missing evidence before drawing a conclusion.', false);
    }
    if (stage === 10 || stage === 11) {
      const view = bundle.investigation;
      const operation = list(view?.rollbacks).at(-1);
      if (stage === 10) {
        const route = knowledgeRoute(records);
        const weight = route?.allocation?.candidate_weight_basis_points;
        return operation ? finding(`Rollback operation: ${operation.status}`, [fact('Target release', operation.target_release_id), fact('Candidate traffic', weight == null ? 'Route unavailable' : percent(weight)), fact('Incident state', view.incident.status)], operation.status === 'executed' && weight === 0 ? 'The route changed. Recovery still needs a healthy observation window.' : 'Inspect the operator screen before claiming the route is restored.') : finding('No rollback operation found', [fact('Candidate traffic', weight == null ? 'Route unavailable' : percent(weight))], 'Request a policy-checked rollback in the Incidents console if eligible.', false);
      }
      return view ? finding(`Recovery state: ${view.incident.status}`, [fact('Rollback', operation?.status || 'Not requested'), fact('Recovery decision', operation?.recovery_decision?.outcome || 'No verified recovery decision'), fact('Observation reasons', list(operation?.recovery_decision?.reasons).join(' · ') || 'None recorded')], view.incident.status === 'resolved' ? 'New observations verified recovery.' : 'Execution is not recovery. The live demo can correctly remain in verification.') : finding('No recovery record found', [], 'Seed the scenario before inspecting recovery.', false);
    }
    return finding('No interpretation available', [], 'Open the raw response below.', false);
  }

  root.AgentHubDemoDecisions = {summarize};
  if (typeof module !== 'undefined' && module.exports) module.exports = {summarize};
})(typeof window !== 'undefined' ? window : globalThis);
