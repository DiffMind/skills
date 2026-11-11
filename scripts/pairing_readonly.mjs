/** Reusable, read-only MCP client. Node 18+; no dependencies or credential output. */
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

class ClientError extends Error {
  constructor(code) { super(code); this.code = code; }
}

/** Remove credentials from tool data as well as client diagnostics. */
function safe(value, token) {
  if (typeof value === 'string') return value.split(token).join('[REDACTED]')
    .replace(/dm_(?:pair|oauth|refresh)_[A-Za-z0-9_-]+/g, '[REDACTED]');
  if (Array.isArray(value)) return value.map(item => safe(item, token));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !/authorization|token|secret|password|cookie|pairingcode/i.test(key))
    .map(([key, item]) => [key, safe(item, token)]));
  return value;
}

/** Parse JSON or SSE without displaying response headers or raw errors. */
export function rpcMessage(body, id) {
  const text = body.replace(/^\uFEFF/, '').trim();
  let messages;
  if (text.startsWith('{')) messages = [JSON.parse(text)];
  else messages = text.split(/\r?\n\r?\n/).flatMap(event => {
    const data = event.split(/\r?\n/).filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart()).join('\n');
    return !data || data === '[DONE]' ? [] : [JSON.parse(data)];
  });
  const result = messages.find(item => item.id === id);
  if (!result || result.jsonrpc !== '2.0') throw new ClientError('invalid_rpc_response');
  if (result.error) throw new ClientError(`rpc_error_${Number(result.error.code) || 0}`);
  if (!Object.hasOwn(result, 'result')) throw new ClientError('missing_rpc_result');
  return result.result;
}

/** Read the already selected config once; never exchange codes or modify connections. */
export async function run({ config, server = 'diffmind-open', models = false }, fetcher = fetch) {
  const entries = JSON.parse(await readFile(config, 'utf8'));
  const entry = entries.mcpServers?.[server];
  if (entry?.url !== 'https://mcp.diffmind.ai/mcp/open') throw new ClientError('configuration_target_mismatch');
  const auth = Object.entries(entry.headers || {}).find(([key]) => key.toLowerCase() === 'authorization')?.[1];
  if (typeof auth !== 'string' || !/^Bearer dm_pair_[A-Za-z0-9_-]+$/.test(auth)) {
    throw new ClientError('pairing_credential_not_configured');
  }
  const token = auth.slice(7);
  let session, protocol, nextId = 1;
  async function rpc(method, params, notification = false) {
    const id = notification ? undefined : nextId++;
    const headers = { Authorization: auth, 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' };
    if (session) headers['Mcp-Session-Id'] = session;
    if (protocol) headers['MCP-Protocol-Version'] = protocol;
    const response = await fetcher(entry.url, {
      method: 'POST', headers, redirect: 'error', signal: AbortSignal.timeout(15000),
      body: JSON.stringify({ jsonrpc: '2.0', ...(notification ? {} : { id }), method, params }),
    });
    if (!response.ok) throw new ClientError(`http_${response.status}`);
    if (method === 'initialize') session = response.headers.get('mcp-session-id') || undefined;
    if (notification) { await response.body?.cancel(); return; }
    const type = response.headers.get('content-type') || '';
    if (!/application\/json|text\/event-stream/i.test(type)) throw new ClientError('unexpected_content_type');
    // Consume SSE only through this request's response; do not wait for stream closure.
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let body = '';
    try {
      while (true) {
        const { value, done } = await reader.read();
        body += decoder.decode(value, { stream: !done });
        if (body.length > 8 * 1024 * 1024) throw new ClientError('response_too_large');
        if (done || /text\/event-stream/i.test(type) && /\r?\n\r?\n/.test(body)) {
          try { return rpcMessage(body, id); }
          catch (error) { if (done || error.code?.startsWith('rpc_error_')) throw error; }
        }
      }
    } finally { await reader.cancel().catch(() => {}); }
  }
  const initialized = await rpc('initialize', {
    protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'diffmind-pairing-readonly', version: '1.0' },
  });
  protocol = initialized.protocolVersion;
  if (!protocol) throw new ClientError('missing_protocol_version');
  await rpc('notifications/initialized', {}, true);
  const tools = [];
  const cursors = new Set();
  let cursor;
  do {
    const page = await rpc('tools/list', cursor ? { cursor } : {});
    if (!Array.isArray(page.tools)) throw new ClientError('invalid_tool_catalog');
    tools.push(...page.tools);
    cursor = page.nextCursor;
    if (cursor && cursors.has(cursor)) throw new ClientError('repeated_tool_cursor');
    if (cursor) cursors.add(cursor);
    if (cursors.size > 100) throw new ClientError('tool_catalog_too_large');
  } while (cursor);
  if (!models) return safe({ ok: true, tools: tools.map(item => ({ name: item.name, inputSchema: item.inputSchema })) }, token);
  const schema = tools.find(item => item.name === 'diffmind_models_list')?.inputSchema;
  if (!schema || schema.type !== 'object') throw new ClientError('model_list_schema_unavailable');
  if (schema.required?.length) throw new ClientError('model_list_requires_arguments');
  const result = await rpc('tools/call', { name: 'diffmind_models_list', arguments: {} });
  if (result.isError) throw new ClientError('model_list_tool_error');
  return safe(result, token);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const args = process.argv.slice(2);
  const value = name => args[args.indexOf(name) + 1];
  if (!args.includes('--config') || args.includes('--models') === args.includes('--check')
      || args.some((arg, index) => !['--config', '--server', '--models', '--check'].includes(arg)
        && !['--config', '--server'].includes(args[index - 1]))) {
    console.error('Usage: node pairing_readonly.mjs --config <mcp.json> [--server <name>] (--models | --check)');
    process.exitCode = 1;
  } else {
    try {
      const result = await run({ config: value('--config'), server: args.includes('--server') ? value('--server') : undefined, models: args.includes('--models') });
      console.log(JSON.stringify(result, null, 2));
    } catch (error) {
      console.error(JSON.stringify({ ok: false, error: error instanceof ClientError ? error.code : 'readonly_client_failed' }));
      process.exitCode = 1;
    }
  }
}
