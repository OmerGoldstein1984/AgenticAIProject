import {
  INodeType,
  INodeTypeDescription,
  IExecuteFunctions,
  INodeExecutionData,
  NodeConnectionType,
} from 'n8n-workflow';

export class SettlementWorker implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Settlement Worker',
    name: 'settlementWorker',
    icon: 'file:settlement-worker.svg',
    group: ['transform'],
    version: 1,
    subtitle: '={{$parameter["ruleSetVersion"]}}',
    description: 'Executes settlement rules using a DSL rule engine with audit trail',
    defaults: {
      name: 'Settlement Worker',
    },
    inputs: [NodeConnectionType.Main],
    outputs: [
      NodeConnectionType.Main, // Settled bets
      NodeConnectionType.Main, // Pending review
      NodeConnectionType.Main, // Errors
    ],
    outputNames: ['Settled', 'Pending Review', 'Errors'],
    properties: [
      {
        displayName: 'Rule Set Version',
        name: 'ruleSetVersion',
        type: 'string',
        default: 'v1.0.0',
        description: 'Version of the settlement rule set to use',
      },
      {
        displayName: 'Rule Set Source',
        name: 'ruleSetSource',
        type: 'options',
        options: [
          { name: 'Embedded JSON', value: 'embedded' },
          { name: 'Database', value: 'database' },
          { name: 'Remote Config', value: 'remote' },
        ],
        default: 'embedded',
        description: 'Where to load the rule set from',
      },
      {
        displayName: 'Embedded Rule Set',
        name: 'embeddedRuleSet',
        type: 'json',
        default: '{\n  "version": "v1.0.0",\n  "defaultOutcome": "void",\n  "rules": [\n    {\n      "id": "goal_home_win",\n      "name": "Home Team Wins",\n      "priority": 10,\n      "condition": { "operator": "and", "conditions": [\n        { "field": "event.status", "comparator": "eq", "value": "ended" },\n        { "field": "event.score.home", "comparator": "gt", "value": "{{$json.event.score.away}}" }\n      ]},\n      "outcome": "won",\n      "metadata": { "selection": "home_win" }\n    },\n    {\n      "id": "goal_away_win",\n      "name": "Away Team Wins",\n      "priority": 10,\n      "condition": { "operator": "and", "conditions": [\n        { "field": "event.status", "comparator": "eq", "value": "ended" },\n        { "field": "event.score.away", "comparator": "gt", "value": "{{$json.event.score.home}}" }\n      ]},\n      "outcome": "won",\n      "metadata": { "selection": "away_win" }\n    },\n    {\n      "id": "draw",\n      "name": "Match Drawn",\n      "priority": 10,\n      "condition": { "operator": "and", "conditions": [\n        { "field": "event.status", "comparator": "eq", "value": "ended" },\n        { "field": "event.score.home", "comparator": "eq", "value": "{{$json.event.score.away}}" }\n      ]},\n      "outcome": "won",\n      "metadata": { "selection": "draw" }\n    },\n    {\n      "id": "match_cancelled",\n      "name": "Match Cancelled",\n      "priority": 5,\n      "condition": { "field": "event.status", "comparator": "eq", "value": "cancelled" },\n      "outcome": "void"\n    },\n    {\n      "id": "match_postponed",\n      "name": "Match Postponed",\n      "priority": 5,\n      "condition": { "field": "event.status", "comparator": "eq", "value": "postponed" },\n      "outcome": "void"\n    },\n    {\n      "id": "match_abandoned",\n      "name": "Match Abandoned",\n      "priority": 5,\n      "condition": { "field": "event.status", "comparator": "eq", "value": "abandoned" },\n      "outcome": "void"\n    }\n  ]\n}',
        displayOptions: {
          show: {
            ruleSetSource: ['embedded'],
          },
        },
        description: 'Settlement rule set in JSON format (DSL)',
      },
      {
        displayName: 'Bet Data Field',
        name: 'betDataField',
        type: 'string',
        default: 'bet',
        description: 'Field containing bet data (selection, stake, etc.)',
      },
      {
        displayName: 'Event Data Field',
        name: 'eventDataField',
        type: 'string',
        default: 'event',
        description: 'Field containing event data (score, status, etc.)',
      },
      {
        displayName: 'Confidence Threshold',
        name: 'confidenceThreshold',
        type: 'number',
        default: 0.95,
        description: 'Minimum confidence to auto-settle (below goes to review)',
      },
      {
        displayName: 'Partial Settlement',
        name: 'partialSettlement',
        type: 'collection',
        placeholder: 'Add Setting',
        default: {},
        options: [
          {
            displayName: 'Enable',
            name: 'enabled',
            type: 'boolean',
            default: true,
          },
          {
            displayName: 'Min Confidence for Partial',
            name: 'minConfidence',
            type: 'number',
            default: 0.7,
          },
        ],
      },
      {
        displayName: 'Audit Trail',
        name: 'auditTrail',
        type: 'collection',
        placeholder: 'Add Setting',
        default: {},
        options: [
          {
            displayName: 'Enable',
            name: 'enabled',
            type: 'boolean',
            default: true,
          },
          {
            displayName: 'Include Rule Evaluation Trace',
            name: 'includeTrace',
            type: 'boolean',
            default: true,
          },
          {
            displayName: 'Output Audit Field',
            name: 'outputField',
            type: 'string',
            default: '_audit',
          },
        ],
      },
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const settledOutput: INodeExecutionData[] = [];
    const pendingReviewOutput: INodeExecutionData[] = [];
    const errorOutput: INodeExecutionData[] = [];

    const ruleSetSource = this.getNodeParameter('ruleSetSource', 0) as string;
    const ruleSetVersion = this.getNodeParameter('ruleSetVersion', 0) as string;
    const betDataField = this.getNodeParameter('betDataField', 0) as string;
    const eventDataField = this.getNodeParameter('eventDataField', 0) as string;
    const confidenceThreshold = this.getNodeParameter('confidenceThreshold', 0) as number;
    const partialSettlement = this.getNodeParameter('partialSettlement', 0) as {
      enabled: boolean;
      minConfidence: number;
    };
    const auditTrail = this.getNodeParameter('auditTrail', 0) as {
      enabled: boolean;
      includeTrace: boolean;
      outputField: string;
    };

    // Load rule set
    let ruleSet: any;
    if (ruleSetSource === 'embedded') {
      const embedded = this.getNodeParameter('embeddedRuleSet', 0) as string;
      try {
        ruleSet = JSON.parse(embedded);
      } catch (e) {
        // If not valid JSON, use default
        ruleSet = this.getDefaultRuleSet();
      }
    } else {
      // In production, load from database or remote config
      ruleSet = this.getDefaultRuleSet();
    }

    // Validate rule set version matches
    if (ruleSet.version !== ruleSetVersion) {
      console.warn(`Rule set version mismatch: expected ${ruleSetVersion}, got ${ruleSet.version}`);
    }

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const data = item.json;

      const bet = data[betDataField];
      const event = data[eventDataField];

      if (!bet || !event) {
        errorOutput.push({
          json: {
            ...data,
            _settlementError: `Missing required fields: bet (${!!bet}), event (${!!event})`,
            _processedAt: new Date().toISOString(),
          },
          pairedItem: { item: i },
        });
        continue;
      }

      // Evaluate rules
      const evaluation = this.evaluateRules(ruleSet, bet, event, auditTrail.includeTrace);

      // Determine outcome
      let outcome = ruleSet.defaultOutcome;
      let confidence = 0.5;
      let matchedRule: any = null;

      if (evaluation.matchedRule) {
        outcome = evaluation.matchedRule.outcome;
        confidence = evaluation.confidence;
        matchedRule = evaluation.matchedRule;
      }

      // Build settlement result
      const settlementResult = {
        ...data,
        settlement: {
          eventId: event.id,
          marketId: bet.marketId || bet.market_id,
          selectionId: bet.selectionId || bet.selection_id,
          outcome,
          settledAt: new Date().toISOString(),
          source: confidence >= confidenceThreshold ? 'auto' : 'pending_review',
          confidence,
          matchedRuleId: matchedRule?.id,
          ruleSetVersion: ruleSet.version,
        },
      };

      // Add audit trail
      if (auditTrail.enabled) {
        settlementResult[auditTrail.outputField] = {
          ruleSetVersion: ruleSet.version,
          evaluatedRules: evaluation.evaluatedRules,
          matchedRule: matchedRule?.id,
          confidenceCalculation: evaluation.confidenceBreakdown,
          timestamp: new Date().toISOString(),
        };
      }

      // Route based on confidence
      if (confidence >= confidenceThreshold) {
        settledOutput.push({
          json: settlementResult,
          pairedItem: { item: i },
        });
      } else if (partialSettlement.enabled && confidence >= partialSettlement.minConfidence) {
        // Partial settlement - flag for review but include tentative outcome
        settlementResult.settlement.source = 'partial_auto';
        settlementResult.settlement.requiresReview = true;
        pendingReviewOutput.push({
          json: settlementResult,
          pairedItem: { item: i },
        });
      } else {
        // Full review required
        settlementResult.settlement.source = 'manual_review';
        settlementResult.settlement.requiresReview = true;
        pendingReviewOutput.push({
          json: settlementResult,
          pairedItem: { item: i },
        });
      }
    }

    return [settledOutput, pendingReviewOutput, errorOutput];
  }

  private getDefaultRuleSet(): any {
    return {
      version: 'v1.0.0',
      defaultOutcome: 'void',
      rules: [
        {
          id: 'goal_home_win',
          name: 'Home Team Wins',
          priority: 10,
          condition: {
            operator: 'and',
            conditions: [
              { field: 'event.status', comparator: 'eq', value: 'ended' },
              { field: 'event.score.home', comparator: 'gt', value: '{{$json.event.score.away}}' },
            ],
          },
          outcome: 'won',
          metadata: { selection: 'home_win' },
        },
        {
          id: 'goal_away_win',
          name: 'Away Team Wins',
          priority: 10,
          condition: {
            operator: 'and',
            conditions: [
              { field: 'event.status', comparator: 'eq', value: 'ended' },
              { field: 'event.score.away', comparator: 'gt', value: '{{$json.event.score.home}}' },
            ],
          },
          outcome: 'won',
          metadata: { selection: 'away_win' },
        },
        {
          id: 'draw',
          name: 'Match Drawn',
          priority: 10,
          condition: {
            operator: 'and',
            conditions: [
              { field: 'event.status', comparator: 'eq', value: 'ended' },
              { field: 'event.score.home', comparator: 'eq', value: '{{$json.event.score.away}}' },
            ],
          },
          outcome: 'won',
          metadata: { selection: 'draw' },
        },
        {
          id: 'match_cancelled',
          name: 'Match Cancelled',
          priority: 5,
          condition: { field: 'event.status', comparator: 'eq', value: 'cancelled' },
          outcome: 'void',
        },
        {
          id: 'match_postponed',
          name: 'Match Postponed',
          priority: 5,
          condition: { field: 'event.status', comparator: 'eq', value: 'postponed' },
          outcome: 'void',
        },
        {
          id: 'match_abandoned',
          name: 'Match Abandoned',
          priority: 5,
          condition: { field: 'event.status', comparator: 'eq', value: 'abandoned' },
          outcome: 'void',
        },
      ],
    };
  }

  private evaluateRules(ruleSet: any, bet: any, event: any, includeTrace: boolean): any {
    const evaluatedRules: any[] = [];
    let matchedRule: any = null;
    let highestPriority = -1;

    // Combine bet and event for rule evaluation
    const context = { bet, event };

    // Sort rules by priority (highest first)
    const sortedRules = [...ruleSet.rules].sort((a, b) => (b.priority || 0) - (a.priority || 0));

    for (const rule of sortedRules) {
      const trace: any = {
        ruleId: rule.id,
        ruleName: rule.name,
        priority: rule.priority,
        matched: false,
      };

      const conditionResult = this.evaluateCondition(rule.condition, context, bet, event);

      if (includeTrace) {
        trace.conditionResult = conditionResult;
        trace.matched = conditionResult.matched;
      }

      evaluatedRules.push(trace);

      if (conditionResult.matched) {
        if ((rule.priority || 0) > highestPriority) {
          matchedRule = rule;
          highestPriority = rule.priority || 0;
        }
      }
    }

    // Calculate confidence based on rule match quality
    let confidence = 0.5;
    let confidenceBreakdown: any = { base: 0.5 };

    if (matchedRule) {
      // Base confidence from rule priority (normalized)
      const maxPriority = Math.max(...ruleSet.rules.map((r: any) => r.priority || 0));
      confidence = 0.5 + 0.4 * (matchedRule.priority / maxPriority);
      confidenceBreakdown = {
        base: 0.5,
        priorityBonus: 0.4 * (matchedRule.priority / maxPriority),
        ruleId: matchedRule.id,
      };

      // Boost confidence for exact score matches
      if (matchedRule.condition?.conditions) {
        const hasExactScore = matchedRule.condition.conditions.some(
          (c: any) => c.field?.includes('score') && c.comparator === 'eq'
        );
        if (hasExactScore) {
          confidence += 0.1;
          confidenceBreakdown.exactScoreBonus = 0.1;
        }
      }

      confidence = Math.min(confidence, 1.0);
    }

    return {
      matchedRule,
      confidence,
      confidenceBreakdown,
      evaluatedRules: includeTrace ? evaluatedRules : [],
    };
  }

  private evaluateCondition(condition: any, context: any, bet: any, event: any): any {
    // Handle compound conditions (and/or/not)
    if (condition.operator) {
      const conditions = condition.conditions || [];
      const results = conditions.map((c: any) => this.evaluateCondition(c, context, bet, event));

      switch (condition.operator) {
        case 'and':
          return { matched: results.every((r: any) => r.matched), details: results };
        case 'or':
          return { matched: results.some((r: any) => r.matched), details: results };
        case 'not':
          return { matched: !results[0]?.matched, details: results };
        default:
          return { matched: false };
      }
    }

    // Handle simple field comparison
    if (condition.field && condition.comparator) {
      const fieldValue = this.getFieldValue(condition.field, context, bet, event);
      const expectedValue = this.resolveValue(condition.value, context, bet, event);

      const matched = this.compare(fieldValue, condition.comparator, expectedValue);

      return {
        matched,
        field: condition.field,
        comparator: condition.comparator,
        actual: fieldValue,
        expected: expectedValue,
      };
    }

    return { matched: false };
  }

  private getFieldValue(fieldPath: string, context: any, bet: any, event: any): any {
    // Handle template expressions like {{$json.event.score.away}}
    if (typeof fieldPath === 'string' && fieldPath.includes('{{')) {
      return this.resolveValue(fieldPath, context, bet, event);
    }

    // Standard dot notation path
    const parts = fieldPath.split('.');
    let current: any = context;

    for (const part of parts) {
      if (part === 'bet') current = bet;
      else if (part === 'event') current = event;
      else current = current?.[part];
    }

    return current;
  }

  private resolveValue(value: any, context: any, bet: any, event: any): any {
    if (typeof value !== 'string' || !value.includes('{{')) {
      return value;
    }

    // Simple template resolution: {{$json.event.score.away}} -> event.score.away
    const match = value.match(/\{\{\s*\$json\.(\w+(?:\.\w+)*)\s*\}\}/);
    if (match) {
      const path = match[1];
      return this.getFieldValue(path, context, bet, event);
    }

    return value;
  }

  private compare(actual: any, comparator: string, expected: any): boolean {
    switch (comparator) {
      case 'eq':
        return actual === expected;
      case 'ne':
        return actual !== expected;
      case 'gt':
        return Number(actual) > Number(expected);
      case 'gte':
        return Number(actual) >= Number(expected);
      case 'lt':
        return Number(actual) < Number(expected);
      case 'lte':
        return Number(actual) <= Number(expected);
      case 'in':
        return Array.isArray(expected) && expected.includes(actual);
      case 'contains':
        return String(actual).includes(String(expected));
      default:
        return false;
    }
  }
}