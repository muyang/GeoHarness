/** 会话面板的纯逻辑：工具表、确认分类、循环归约。可单测，不碰 DOM/网络。
 *
 *  人在环纪律：读工具（capabilities/describe）自动放行；
 *  执行类（execute/plan）必须先展示参数、由人点确认才真的发出去。
 */

export const CONFIRM_TOOLS = new Set(['geo_execute', 'geo_plan'])

export function buildTools(caps) {
  const skills = (caps?.skills || []).map((s) => s.name)
  return [
    {
      type: 'function',
      function: {
        name: 'geo_capabilities',
        description: '列出节点的技能、GeoCards 与 V2 能力（只读）',
        parameters: { type: 'object', properties: {}, additionalProperties: false }
      }
    },
    {
      type: 'function',
      function: {
        name: 'geo_describe',
        description: '查看指定 GeoCards 的合约详情（只读）',
        parameters: {
          type: 'object',
          properties: { geocards: { type: 'array', items: { type: 'string' } } },
          required: ['geocards'], additionalProperties: false
        }
      }
    },
    {
      type: 'function',
      function: {
        name: 'geo_execute',
        description: `在节点上执行一个技能（会占用算力，需人工确认）。可选技能：${skills.join(', ') || '（无）'}`,
        parameters: {
          type: 'object',
          properties: {
            skill: { type: 'string', enum: skills.length ? skills : undefined },
            params: { type: 'object', description: '技能参数（JSON 对象）' },
            geocards: { type: 'array', items: { type: 'string' } },
            bbox: { type: 'array', items: { type: 'number' }, description: '可选 [西,南,东,北]' },
            contract_binding: { type: 'string', description: '可选 GAAG 合约 id' }
          },
          required: ['skill'], additionalProperties: false
        }
      }
    },
    {
      type: 'function',
      function: {
        name: 'geo_plan',
        description: '物化一个 recipe 的任务图（只规划不执行，需人工确认）',
        parameters: {
          type: 'object',
          properties: { recipe: { type: 'string' }, params: { type: 'object' } },
          required: ['recipe'], additionalProperties: false
        }
      }
    }
  ]
}

export function needsConfirm(toolName) {
  return CONFIRM_TOOLS.has(toolName)
}

/** 把一次 assistant 回复归约成待办工具调用列表（纯函数）。 */
export function pendingCalls(assistantMessage) {
  const calls = assistantMessage?.tool_calls || []
  return calls.map((c) => {
    let args = {}
    try { args = JSON.parse(c.function?.arguments || '{}') } catch { args = { __raw: c.function?.arguments } }
    return { id: c.id, name: c.function?.name, args }
  })
}

/** 执行一个工具调用（client 由调用方注入，便于测试与多节点）。 */
export async function runTool(client, name, args) {
  if (name === 'geo_capabilities') return client.capabilities()
  if (name === 'geo_describe') return client.describe(args.geocards || [])
  if (name === 'geo_execute') {
    const spatial = Array.isArray(args.bbox) && args.bbox.length === 4
      ? { bbox: args.bbox, crs: 'EPSG:4326' } : null
    return client.execute(args.skill, {
      params: args.params || {}, geocards: args.geocards || [], spatial,
      contractBinding: args.contract_binding || null
    })
  }
  if (name === 'geo_plan') return client.plan(args.recipe, args.params || {})
  throw new Error(`未知工具：${name}`)
}
