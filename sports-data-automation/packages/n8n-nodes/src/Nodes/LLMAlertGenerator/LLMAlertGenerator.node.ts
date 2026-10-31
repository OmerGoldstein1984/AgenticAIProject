import {
  INodeType,
  INodeTypeDescription,
  IExecuteFunctions,
  INodeExecutionData,
  NodeConnectionType,
} from 'n8n-workflow';

export class LLMAlertGenerator implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'LLM Alert Generator',
    name: 'llmAlertGenerator',
    icon: 'file:llm-alert-generator.svg',
    group: ['transform'],
    version: 1,
    subtitle: '={{$parameter["model"]}}',
    description: 'Generates human-readable alerts from anomalies using LLM with structured output and confidence scoring',
    defaults: {
      name: 'LLM Alert Generator',
    },
    inputs: [NodeConnectionType.Main],
    outputs: [
      NodeConnectionType.Main, // High confidence alerts (auto-escalate)
      NodeConnectionType.Main, // Low confidence alerts (human review)
      NodeConnectionType.Main, // Errors
    ],
    outputNames: ['Auto-Escalate', 'Human Review', 'Errors'],
    properties: [
      {
        displayName: 'LLM Provider',
        name: 'provider',
        type: 'options',
        options: [
          { name: 'Anthropic (Claude)', value: 'anthropic' },
          { name: 'OpenAI', value: 'openai' },
        ],
        default: 'anthropic',
        description: 'LLM provider to use for alert generation',
      },
      {
        displayName: 'Model',
        name: 'model',
        type: 'options',
        options: [
          { name: 'Claude 3.5 Sonnet', value: 'claude-3-5-sonnet-20241022' },
          { name: 'Claude 3.5 Haiku', value: 'claude-3-5-haiku-20241022' },
          { name: 'GPT-4o', value: 'gpt-4o' },
          { name: 'GPT-4o Mini', value: 'gpt-4o-mini' },
        ],
        default: 'claude-3-5-sonnet-20241022',
        description: 'Model to use for alert generation',
      },
      {
        displayName: 'API Key',
        name: 'apiKey',
        type: 'string',
        typeOptions: {
          password: true,
        },
        default: '',
        description: 'API key for LLM provider (or set via environment variable)',
      },
      {
        displayName: 'Anomaly Type',
        name: 'anomalyType',
        type: 'options',
        options: [
          { name: 'Odds Anomaly', value: 'odds_anomaly' },
          { name: 'Settlement Discrepancy', value: 'settlement_discrepancy' },
          { name: 'Feed Outage', value: 'feed_outage' },
          { name: 'Arbitrage Detected', value: 'arbitrage_detected' },
          { name: 'Suspicious Pattern', value: 'suspicious_pattern' },
          { name: 'Reconciliation Drift', value: 'reconciliation_drift' },
        ],
        default: 'odds_anomaly',
        description: 'Type of anomaly to generate alert for',
      },
      {
        displayName: 'Confidence Threshold',
        name: 'confidenceThreshold',
        type: 'number',
        default: 0.8,
        description: 'Minimum confidence to auto-escalate (below goes to human review)',
      },
      {
        displayName: 'Few-Shot Examples',
        name: 'fewShotExamples',
        type: 'json',
        default: '[\n  {\n    "input": {\n      "anomalyType": "odds_anomaly",\n      "eventData": {\n        "id": "evt_123",\n        "sport": "football",\n        "league": "Premier League",\n        "homeTeam": { "name": "Arsenal" },\n        "awayTeam": { "name": "Chelsea" },\n        "status": "live"\n      },\n      "anomalyDetails": {\n        "provider": "provider_a",\n        "odds": 1.5,\n        "marketAverage": 2.1,\n        "deviation": "33% below market"\n      }\n    },\n    "output": {\n      "title": "Significant Odds Deviation: Arsenal vs Chelsea",\n      "description": "Provider A offering 1.50 on Arsenal (home win) vs market average 2.10. 33% deviation suggests potential error or insider information. Match: Arsenal vs Chelsea, Premier League, currently live.",\n      "severity": "warning",\n      "confidence": 0.92,\n      "suggestedAction": "Verify with other providers; consider suspending market if confirmed error",\n      "metadata": { "deviationPercent": 33, "market": "match_winner" }\n    }\n  },\n  {\n    "input": {\n      "anomalyType": "settlement_discrepancy",\n      "eventData": {\n        "id": "evt_456",\n        "sport": "tennis",\n        "league": "ATP 250",\n        "homeTeam": { "name": "Player A" },\n        "awayTeam": { "name": "Player B" },\n        "status": "ended",\n        "score": { "home": 2, "away": 1 }\n      },\n      "anomalyDetails": {\n        "autoSettled": "won",\n        "officialResult": "void",\n        "reason": "Match retired at 2-1 sets"\n      }\n    },\n    "output": {\n      "title": "Settlement Discrepancy: Player A vs Player B",\n      "description": "Auto-settlement marked as 'won' for Player A but official result is 'void' due to retirement at 2-1 sets. Tennis rules require match completion for settlement. Affected bets on match winner market.",\n      "severity": "critical",\n      "confidence": 0.98,\n      "suggestedAction": "Immediately void affected settlements; notify customers; investigate rule engine gap",\n      "metadata": { "sport": "tennis", "ruleGap": "retirement_handling" }\n    }\n  }\n]',
        description: 'Few-shot examples for LLM prompt (JSON array of input/output pairs)',
      },
      {
        displayName: 'Custom System Prompt',
        name: 'systemPrompt',
        type: 'string',
        default: '',
        description: 'Optional custom system prompt (appends to default)',
      },
      {
        displayName: 'Output Schema',
        name: 'outputSchema',
        type: 'json',
        default: '{\n  "type": "object",\n  "properties": {\n    "title": { "type": "string" },\n    "description": { "type": "string" },\n    "severity": { "type": "string", "enum": ["info", "warning", "critical", "page"] },\n    "confidence": { "type": "number", "minimum": 0, "maximum": 1 },\n    "suggestedAction": { "type": "string" },\n    "metadata": { "type": "object" }\n  },\n  "required": ["title", "description", "severity", "confidence"]\n}',
        description: 'JSON Schema for structured LLM output',
      },
      {
        displayName: 'Temperature',
        name: 'temperature',
        type: 'number',
        default: 0.1,
        description: 'LLM temperature (low for consistent structured output)',
      },
      {
        displayName: 'Max Tokens',
        name: 'maxTokens',
        type: 'number',
        default: 500,
      },
      {
        displayName: 'Rule-Based Baseline',
        name: 'ruleBasedBaseline',
        type: 'collection',
        placeholder: 'Add Setting',
        default: {},
        options: [
          {
            displayName: 'Enable Comparison',
            name: 'enabled',
            type: 'boolean',
            default: true,
            description: 'Compare LLM output against rule-based baseline',
          },
          {
            displayName: 'Agreement Threshold',
            name: 'agreementThreshold',
            type: 'number',
            default: 0.8,
            description: 'Minimum agreement score to trust LLM (below flags for review)',
          },
        ],
      },
      {
        displayName: 'Human Review Queue',
        name: 'humanReviewQueue',
        type: 'collection',
        placeholder: 'Add Setting',
        default: {},
        options: [
          {
            displayName: 'Queue Name',
            name: 'queueName',
            type: 'string',
            default: 'alerts:human_review',
          },
          {
            displayName: 'Include LLM Reasoning',
            name: 'includeReasoning',
            type: 'boolean',
            default: true,
          },
          {
            displayName: 'Priority by Severity',
            name: 'priorityBySeverity',
            type: 'boolean',
            default: true,
          },
        ],
      },
    ],
  };

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const autoEscalateOutput: INodeExecutionData[] = [];
    const humanReviewOutput: INodeExecutionData[] = [];
    const errorOutput: INodeExecutionData[] = [];

    const provider = this.getNodeParameter('provider', 0) as 'anthropic' | 'openai';
    const model = this.getNodeParameter('model', 0) as string;
    const apiKey = this.getNodeParameter('apiKey', 0) as string || process.env[`${provider.toUpperCase()}_API_KEY`];
    const anomalyType = this.getNodeParameter('anomalyType', 0) as string;
    const confidenceThreshold = this.getNodeParameter('confidenceThreshold', 0) as number;
    const fewShotExamples = this.getNodeParameter('fewShotExamples', 0) as any[];
    const systemPrompt = this.getNodeParameter('systemPrompt', 0) as string;
    const outputSchema = this.getNodeParameter('outputSchema', 0) as any;
    const temperature = this.getNodeParameter('temperature', 0) as number;
    const maxTokens = this.getNodeParameter('maxTokens', 0) as number;
    const ruleBasedBaseline = this.getNodeParameter('ruleBasedBaseline', 0) as {
      enabled: boolean;
      agreementThreshold: number;
    };
    const humanReviewQueue = this.getNodeParameter('humanReviewQueue', 0) as {
      queueName: string;
      includeReasoning: boolean;
      priorityBySeverity: boolean;
    };

    if (!apiKey) {
      // No API key - send all to error output
      for (let i = 0; i < items.length; i++) {
        errorOutput.push({
          json: {
            ...items[i].json,
            _llmError: `No API key configured for ${provider}`,
            _processedAt: new Date().toISOString(),
          },
          pairedItem: { item: i },
        });
      }
      return [autoEscalateOutput, humanReviewOutput, errorOutput];
    }

    // Build system prompt
    const defaultSystemPrompt = this.buildSystemPrompt(anomalyType, outputSchema, fewShotExamples);
    const fullSystemPrompt = systemPrompt ? `${defaultSystemPrompt}\n\n${systemPrompt}` : defaultSystemPrompt;

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const data = item.json;

      // Extract event data and anomaly details
      const eventData = data.eventData || data.event || data;
      const anomalyDetails = data.anomalyDetails || data.details || data;

      // Build user prompt
      const userPrompt = this.buildUserPrompt(anomalyType, eventData, anomalyDetails);

      try {
        // Call LLM
        const llmResponse = await this.callLLM(
          provider,
          model,
          apiKey,
          fullSystemPrompt,
          userPrompt,
          outputSchema,
          temperature,
          maxTokens
        );

        // Parse structured response
        let parsedResponse: any;
        try {
          parsedResponse = JSON.parse(llmResponse);
        } catch {
          // Try to extract JSON from response
          const jsonMatch = llmResponse.match(/\{[\s\S]*\}/);
          if (jsonMatch) {
            parsedResponse = JSON.parse(jsonMatch[0]);
          } else {
            throw new Error('Failed to parse LLM response as JSON');
          }
        }

        // Validate required fields
        if (!parsedResponse.title || !parsedResponse.description || !parsedResponse.severity || parsedResponse.confidence === undefined) {
          throw new Error('LLM response missing required fields');
        }

        // Clamp confidence
        parsedResponse.confidence = Math.max(0, Math.min(1, parsedResponse.confidence));

        // Build alert object
        const alert = {
          id: `alert_${Date.now()}_${i}`,
          type: anomalyType,
          severity: parsedResponse.severity,
          title: parsedResponse.title,
          description: parsedResponse.description,
          sourceEventId: eventData.id,
          confidence: parsedResponse.confidence,
          metadata: {
            ...parsedResponse.metadata,
            suggestedAction: parsedResponse.suggestedAction,
            llmProvider: provider,
            llmModel: model,
            anomalyType,
          },
          createdAt: new Date().toISOString(),
        };

        // Rule-based baseline comparison (simplified)
        let agreed = true;
        if (ruleBasedBaseline.enabled) {
          // In production, this would call a rule-based alert generator
          // For now, simulate agreement
          agreed = parsedResponse.confidence > 0.7; // Simplified
        }

        // Determine routing
        const shouldAutoEscalate = parsedResponse.confidence >= confidenceThreshold && agreed;
        const outputItem = {
          json: {
            ...data,
            alert,
            _llmEvaluation: {
              confidence: parsedResponse.confidence,
              agreed,
              autoEscalate: shouldAutoEscalate,
              evaluatedAt: new Date().toISOString(),
            },
          },
          pairedItem: { item: i },
        };

        if (shouldAutoEscalate) {
          autoEscalateOutput.push(outputItem);
        } else {
          // Add to human review queue metadata
          outputItem.json._humanReview = {
            queue: humanReviewQueue.queueName,
            priority: this.getPriorityFromSeverity(parsedResponse.severity),
            includeReasoning: humanReviewQueue.includeReasoning,
            llmResponse: llmResponse,
          };
          humanReviewOutput.push(outputItem);
        }

      } catch (error: any) {
        errorOutput.push({
          json: {
            ...data,
            _llmError: error.message,
            _processedAt: new Date().toISOString(),
          },
          pairedItem: { item: i },
        });
      }
    }

    return [autoEscalateOutput, humanReviewOutput, errorOutput];
  }

  private buildSystemPrompt(anomalyType: string, outputSchema: any, fewShotExamples: any[]): string {
    const typeDescriptions: Record<string, string> = {
      odds_anomaly: 'Unusual odds movements or deviations from market consensus',
      settlement_discrepancy: 'Difference between automated settlement and official result',
      feed_outage: 'Data provider feed interruption or degradation',
      arbitrage_detected: 'Cross-provider arbitrage opportunity identified',
      suspicious_pattern: 'Betting pattern suggesting potential fraud or manipulation',
      reconciliation_drift: 'Data inconsistency detected during daily reconciliation',
    };

    let prompt = `You are an expert sports betting operations analyst. Generate clear, actionable alerts for: ${typeDescriptions[anomalyType] || anomalyType}.

OUTPUT REQUIREMENTS:
- Respond ONLY with valid JSON matching the provided schema
- Title: Concise, specific, includes key entities (teams, players, match)
- Description: Complete context for on-call engineer - what happened, why it matters, affected markets
- Severity: "info" (FYI), "warning" (investigate), "critical" (immediate action), "page" (wake someone up)
- Confidence: 0.0-1.0, be honest about uncertainty
- Suggested Action: Specific next steps
- Metadata: Additional structured data for automation

FORMAT: Return ONLY the JSON object, no markdown, no explanation.`;

    if (fewShotExamples && fewShotExamples.length > 0) {
      prompt += '\n\nFEW-SHOT EXAMPLES:';
      for (const example of fewShotExamples) {
        prompt += `\n\nInput:\n${JSON.stringify(example.input, null, 2)}\n\nOutput:\n${JSON.stringify(example.output, null, 2)}`;
      }
    }

    prompt += `\n\nOUTPUT SCHEMA:\n${JSON.stringify(outputSchema, null, 2)}`;

    return prompt;
  }

  private buildUserPrompt(anomalyType: string, eventData: any, anomalyDetails: any): string {
    return `Generate alert for ${anomalyType}:

EVENT DATA:
${JSON.stringify(eventData, null, 2)}

ANOMALY DETAILS:
${JSON.stringify(anomalyDetails, null, 2)}`;
  }

  private async callLLM(
    provider: 'anthropic' | 'openai',
    model: string,
    apiKey: string,
    systemPrompt: string,
    userPrompt: string,
    outputSchema: any,
    temperature: number,
    maxTokens: number
  ): Promise<string> {
    // In real implementation, use Anthropic SDK or OpenAI SDK
    // This is a placeholder that simulates the call
    // For production, install @anthropic-ai/sdk or openai package

    if (provider === 'anthropic') {
      // const anthropic = new Anthropic({ apiKey });
      // const response = await anthropic.messages.create({
      //   model,
      //   max_tokens: maxTokens,
      //   temperature,
      //   system: systemPrompt,
      //   messages: [{ role: 'user', content: userPrompt }],
      // });
      // return response.content[0].text;

      // Simulated response for development
      return this.getSimulatedResponse(anomalyType);
    } else {
      // const openai = new OpenAI({ apiKey });
      // const response = await openai.chat.completions.create({
      //   model,
      //   max_tokens: maxTokens,
      //   temperature,
      //   messages: [
      //     { role: 'system', content: systemPrompt },
      //     { role: 'user', content: userPrompt },
      //   ],
      //   response_format: { type: 'json_object' },
      // });
      // return response.choices[0].message.content;

      return this.getSimulatedResponse(anomalyType);
    }
  }

  private getSimulatedResponse(anomalyType: string): string {
    // Simulated responses for development/testing
    const responses: Record<string, string> = {
      odds_anomaly: JSON.stringify({
        title: 'Odds Anomaly Detected',
        description: 'Significant deviation detected in odds from provider vs market average',
        severity: 'warning',
        confidence: 0.85,
        suggestedAction: 'Verify with other providers',
        metadata: { deviationPercent: 25 },
      }),
      settlement_discrepancy: JSON.stringify({
        title: 'Settlement Discrepancy',
        description: 'Auto-settlement outcome differs from official result',
        severity: 'critical',
        confidence: 0.95,
        suggestedAction: 'Review and correct settlements',
        metadata: { sport: 'football' },
      }),
      feed_outage: JSON.stringify({
        title: 'Feed Outage Detected',
        description: 'Data provider feed has stopped delivering updates',
        severity: 'critical',
        confidence: 0.9,
        suggestedAction: 'Switch to backup provider; investigate',
        metadata: { provider: 'provider_a' },
      }),
      arbitrage_detected: JSON.stringify({
        title: 'Arbitrage Opportunity',
        description: 'Cross-provider arbitrage detected with positive margin',
        severity: 'info',
        confidence: 0.88,
        suggestedAction: 'Monitor; consider risk limits',
        metadata: { marginPercent: 1.2 },
      }),
      suspicious_pattern: JSON.stringify({
        title: 'Suspicious Betting Pattern',
        description: 'Unusual betting activity detected on specific market',
        severity: 'warning',
        confidence: 0.75,
        suggestedAction: 'Flag for fraud review',
        metadata: { patternType: 'late_money' },
      }),
      reconciliation_drift: JSON.stringify({
        title: 'Reconciliation Drift',
        description: 'Data inconsistency found between systems during daily reconciliation',
        severity: 'warning',
        confidence: 0.82,
        suggestedAction: 'Run correction job; investigate root cause',
        metadata: { discrepancyCount: 15 },
      }),
    };

    return responses[anomalyType] || responses.odds_anomaly;
  }

  private getPriorityFromSeverity(severity: string): number {
    switch (severity) {
      case 'page': return 1;
      case 'critical': return 2;
      case 'warning': return 3;
      case 'info': return 4;
      default: return 5;
    }
  }
}