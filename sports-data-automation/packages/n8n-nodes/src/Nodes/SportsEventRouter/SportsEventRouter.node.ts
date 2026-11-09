/**
 * packages/n8n-nodes/src/Nodes/SportsEventRouter/SportsEventRouter.node.ts
 *
 * FILE HEADER
 * -----------
 * Business problem this file solves:
 *   Incoming sports events (match start, goal, card, injury, settlement...) arrive from the
 *   ingestion service and must be routed to the right downstream work with the right priority.
 *   A goal in a live Premier League match is time-critical; a routine odds change is not.
 *   SportsEventRouter is an n8n custom node that classifies each event, assigns a priority
 *   (high/normal/low), validates required fields, and emits to one of four outputs — including
 *   a dead-letter output for invalid events — with optional Redis Streams stream-key metadata.
 *
 * Where it sits in the flow:
 *   First n8n node after the ingestion webhook. Receives canonical events from ingestion and
 *   routes them to priority queues so the OddsNormalizer / SettlementWorker / alert nodes get
 *   the events they need, ordered by urgency.
 *
 * What calls it / what it calls:
 *   Called by: n8n workflow engine (execute()), triggered by ingestion webhook events.
 *   Calls: nothing external (pure in-node logic); reads node parameters via getNodeParameter.
 *
 * What breaks if removed:
 *   No priority routing — all events would flow undifferentiated, and time-critical events
 *   (goals, settlements) couldn't be fast-tracked. Invalid events would have no dead-letter
 *   destination.
 *
 * Language conventions:
 *   TypeScript/n8n custom node. Implements INodeType; four Main outputs (High/Normal/Low/Dead
 *   Letter); configuration via node parameters (routing mode, mappings, validation, queue
 *   settings).
 *
 * # GAP: the custom expression evaluator is a hand-rolled regex (evaluateExpression) rather
 *   than n8n's real expression engine — complex expressions won't evaluate. See 07_issues_found.md.
 * # INTERVIEW: four separate outputs let downstream nodes scale independently per priority —
 *   this is the content-based-routing pattern.
 */

import {
  INodeType,
  INodeTypeDescription,
  IExecuteFunctions,
  INodeExecutionData,
  NodeConnectionType,
  INodePropertyOptions,
} from 'n8n-workflow';

export class SportsEventRouter implements INodeType {
  /**
   * n8n node metadata: display name, icon, inputs/outputs, and configurable parameters.
   * Drives the n8n UI configuration panel for this node.
   */
  description: INodeTypeDescription = {
    displayName: 'Sports Event Router',
    name: 'sportsEventRouter',
    icon: 'file:sports-event-router.svg',
    group: ['transform'],
    version: 1,
    subtitle: '={{$parameter["routingMode"]}}',
    description: 'Routes sports events to appropriate workflows based on content with priority queuing',
    defaults: {
      name: 'Sports Event Router',
    },
    inputs: [NodeConnectionType.Main],
    outputs: [
      NodeConnectionType.Main, // High priority
      NodeConnectionType.Main, // Normal priority
      NodeConnectionType.Main, // Low priority
      NodeConnectionType.Main, // Dead letter
    ],
    outputNames: ['High Priority', 'Normal Priority', 'Low Priority', 'Dead Letter'],
    properties: [
      {
        displayName: 'Routing Mode',
        name: 'routingMode',
        type: 'options',
        options: [
          { name: 'Event Type', value: 'eventType' },
          { name: 'Sport/League', value: 'sportLeague' },
          { name: 'Priority Field', value: 'priorityField' },
          { name: 'Custom Expression', value: 'customExpression' },
        ],
        default: 'eventType',
        description: 'How to route incoming events',
      },
      {
        displayName: 'Event Type Mapping',
        name: 'eventTypeMapping',
        type: 'fixedCollection',
        typeOptions: {
          multipleValues: true,
        },
        displayOptions: {
          show: {
            routingMode: ['eventType'],
          },
        },
        default: {},
        options: [
          {
            name: 'mapping',
            displayName: 'Mapping',
            values: [
              {
                displayName: 'Event Type',
                name: 'eventType',
                type: 'options',
                options: [
                  { name: 'Match Start', value: 'match_start' },
                  { name: 'Goal', value: 'goal' },
                  { name: 'Card', value: 'card' },
                  { name: 'Substitution', value: 'substitution' },
                  { name: 'Injury', value: 'injury' },
                  { name: 'Half Time', value: 'half_time' },
                  { name: 'Match End', value: 'match_end' },
                  { name: 'Odds Change', value: 'odds_change' },
                  { name: 'Settlement', value: 'settlement' },
                  { name: 'Custom', value: 'custom' },
                ],
                default: 'goal',
              },
              {
                displayName: 'Priority',
                name: 'priority',
                type: 'options',
                options: [
                  { name: 'High', value: 'high' },
                  { name: 'Normal', value: 'normal' },
                  { name: 'Low', value: 'low' },
                ],
                default: 'normal',
              },
              {
                displayName: 'Output Index',
                name: 'outputIndex',
                type: 'number',
                default: 1,
                description: 'Which output to route to (0=High, 1=Normal, 2=Low, 3=Dead Letter)',
              },
            ],
          },
        ],
      },
      {
        displayName: 'Sport/League Mapping',
        name: 'sportLeagueMapping',
        type: 'fixedCollection',
        typeOptions: {
          multipleValues: true,
        },
        displayOptions: {
          show: {
            routingMode: ['sportLeague'],
          },
        },
        default: {},
        options: [
          {
            name: 'mapping',
            displayName: 'Mapping',
            values: [
              {
                displayName: 'Sport',
                name: 'sport',
                type: 'string',
                default: 'football',
              },
              {
                displayName: 'League',
                name: 'league',
                type: 'string',
                default: '',
                description: 'Leave empty for all leagues in sport',
              },
              {
                displayName: 'Priority',
                name: 'priority',
                type: 'options',
                options: [
                  { name: 'High', value: 'high' },
                  { name: 'Normal', value: 'normal' },
                  { name: 'Low', value: 'low' },
                ],
                default: 'normal',
              },
              {
                displayName: 'Output Index',
                name: 'outputIndex',
                type: 'number',
                default: 1,
              },
            ],
          },
        ],
      },
      {
        displayName: 'Priority Field Path',
        name: 'priorityFieldPath',
        type: 'string',
        default: 'metadata.priority',
        displayOptions: {
          show: {
            routingMode: ['priorityField'],
          },
        },
        description: 'JSON path to priority field in event data (e.g., metadata.priority)',
      },
      {
        displayName: 'Custom Expression',
        name: 'customExpression',
        type: 'string',
        default: '{{ $json.metadata.priority === "critical" ? "high" : "normal" }}',
        displayOptions: {
          show: {
            routingMode: ['customExpression'],
          },
        },
        description: 'Expression that returns "high", "normal", or "low"',
      },
      {
        displayName: 'Priority Queue Settings',
        name: 'priorityQueueSettings',
        type: 'collection',
        placeholder: 'Add Setting',
        default: {},
        options: [
          {
            displayName: 'Enable Redis Streams Priority',
            name: 'enableRedisPriority',
            type: 'boolean',
            default: true,
            description: 'Add priority metadata for Redis Streams consumer groups',
          },
          {
            displayName: 'High Priority Stream Key',
            name: 'highPriorityStream',
            type: 'string',
            default: 'sports:events:high',
          },
          {
            displayName: 'Normal Priority Stream Key',
            name: 'normalPriorityStream',
            type: 'string',
            default: 'sports:events:normal',
          },
          {
            displayName: 'Low Priority Stream Key',
            name: 'lowPriorityStream',
            type: 'string',
            default: 'sports:events:low',
          },
          {
            displayName: 'Dead Letter Stream Key',
            name: 'deadLetterStream',
            type: 'string',
            default: 'sports:events:dlq',
          },
        ],
      },
      {
        displayName: 'Validation',
        name: 'validation',
        type: 'collection',
        placeholder: 'Add Setting',
        default: {},
        options: [
          {
            displayName: 'Require Event ID',
            name: 'requireEventId',
            type: 'boolean',
            default: true,
          },
          {
            displayName: 'Require Sport',
            name: 'requireSport',
            type: 'boolean',
            default: true,
          },
          {
            displayName: 'Require Status',
            name: 'requireStatus',
            type: 'boolean',
            default: true,
          },
          {
            displayName: 'Send Invalid to Dead Letter',
            name: 'sendInvalidToDlq',
            type: 'boolean',
            default: true,
          },
        ],
      },
    ],
  };

  /**
   * Main execution: route each input event to one of four priority outputs.
   *
   * WHAT: For every input item, validate required fields (id/sport/status), determine priority
   *   based on the configured routing mode, enrich the event with routing metadata
   *   (priority, streamKey, routedAt, routedBy, originalIndex), and push to the matching output
   *   array (0=High,1=Normal,2=Low,3=Dead Letter).
   * WHY: Content-based routing lets the pipeline treat a live-match goal differently from a
   *   stale odds change, and the dead-letter output isolates bad events without aborting the
   *   whole batch.
   * INPUTS: this.getInputData() — n8n's array of input items (item.json = event data).
   * OUTPUTS: INodeExecutionData[][] — four arrays, one per output (High/Normal/Low/DLQ).
   * SIDE EFFECTS: none outside n8n (no external calls); adds _routing metadata to each event.
   * FAILURE MODES: invalid events → dead-letter output (if sendInvalidToDlq) or silently
   *   skipped; custom-expression parse failure → falls back to normal priority.
   * ALTERNATIVE: route inside n8n using native IF/Switch nodes. Chosen a custom node because
   *   the routing logic (priority stream keys, dead-letter, validation) is sports-specific and
   *   easier to test/version as code.
   * # INTERVIEW: know that output index 0=High … 3=Dead Letter maps to the four declared
   *   outputs — downstream wires depend on this ordering.
   */
  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const returnData: INodeExecutionData[][] = [[], [], [], []]; // High, Normal, Low, DLQ

    const routingMode = this.getNodeParameter('routingMode', 0) as string;
    const validation = this.getNodeParameter('validation', 0) as {
      requireEventId: boolean;
      requireSport: boolean;
      requireStatus: boolean;
      sendInvalidToDlq: boolean;
    };
    const priorityQueueSettings = this.getNodeParameter('priorityQueueSettings', 0) as {
      enableRedisPriority: boolean;
      highPriorityStream: string;
      normalPriorityStream: string;
      lowPriorityStream: string;
      deadLetterStream: string;
    };

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const eventData = item.json;

      // Validate required fields
      const validationErrors: string[] = [];
      if (validation.requireEventId && !eventData.id) {
        validationErrors.push('Missing required field: id');
      }
      if (validation.requireSport && !eventData.sport) {
        validationErrors.push('Missing required field: sport');
      }
      if (validation.requireStatus && !eventData.status) {
        validationErrors.push('Missing required field: status');
      }

      if (validationErrors.length > 0) {
        if (validation.sendInvalidToDlq) {
          returnData[3].push({
            json: {
              ...eventData,
              _routingError: validationErrors.join('; '),
              _routedAt: new Date().toISOString(),
              _originalIndex: i,
            },
            pairedItem: { item: i },
          });
        }
        continue;
      }

      // Determine priority based on routing mode
      let priority: 'high' | 'normal' | 'low' = 'normal';
      let outputIndex = 1; // Default to normal

      switch (routingMode) {
        case 'eventType': {
          const mappings = this.getNodeParameter('eventTypeMapping.mapping', 0, []) as Array<{
            eventType: string;
            priority: 'high' | 'normal' | 'low';
            outputIndex: number;
          }>;
          const eventType = eventData.type || eventData.eventType || 'unknown';
          const mapping = mappings.find(m => m.eventType === eventType);
          if (mapping) {
            priority = mapping.priority;
            outputIndex = Math.min(Math.max(mapping.outputIndex, 0), 3);
          }
          break;
        }
        case 'sportLeague': {
          const mappings = this.getNodeParameter('sportLeagueMapping.mapping', 0, []) as Array<{
            sport: string;
            league: string;
            priority: 'high' | 'normal' | 'low';
            outputIndex: number;
          }>;
          const mapping = mappings.find(m =>
            m.sport === eventData.sport && (m.league === '' || m.league === eventData.league)
          );
          if (mapping) {
            priority = mapping.priority;
            outputIndex = Math.min(Math.max(mapping.outputIndex, 0), 3);
          }
          break;
        }
        case 'priorityField': {
          const fieldPath = this.getNodeParameter('priorityFieldPath', 0) as string;
          const fieldValue = this.getValueAtPath(eventData, fieldPath);
          if (fieldValue === 'high' || fieldValue === 'critical' || fieldValue === 'urgent') {
            priority = 'high';
            outputIndex = 0;
          } else if (fieldValue === 'low') {
            priority = 'low';
            outputIndex = 2;
          } else {
            priority = 'normal';
            outputIndex = 1;
          }
          break;
        }
        case 'customExpression': {
          const expression = this.getNodeParameter('customExpression', 0) as string;
          // In real n8n, this would be evaluated by the expression engine
          // For now, we'll do a simple evaluation
          try {
            // This is simplified - real implementation uses n8n's expression evaluator
            const result = this.evaluateExpression(expression, eventData);
            if (result === 'high') {
              priority = 'high';
              outputIndex = 0;
            } else if (result === 'low') {
              priority = 'low';
              outputIndex = 2;
            } else {
              priority = 'normal';
              outputIndex = 1;
            }
          } catch {
            priority = 'normal';
            outputIndex = 1;
          }
          break;
        }
      }

      // Add routing metadata for downstream consumers
      const enrichedEvent = {
        ...eventData,
        _routing: {
          priority,
          streamKey: priorityQueueSettings.enableRedisPriority
            ? priority === 'high'
              ? priorityQueueSettings.highPriorityStream
              : priority === 'low'
              ? priorityQueueSettings.lowPriorityStream
              : priorityQueueSettings.normalPriorityStream
            : undefined,
          routedAt: new Date().toISOString(),
          routedBy: 'SportsEventRouter',
          originalIndex: i,
        },
      };

      returnData[outputIndex].push({
        json: enrichedEvent,
        pairedItem: { item: i },
      });
    }

    return returnData;
  }

  /**
   * Read a value at a dotted path from an object (e.g. "metadata.priority").
   */
  private getValueAtPath(obj: Record<string, unknown>, path: string): unknown {
    return path.split('.').reduce((current: any, key: string) => current?.[key], obj);
  }

  /**
   * Evaluate a simplified n8n-style expression ({{ $json.a.b === "x" ? "y" : "z" }}).
   * Real n8n uses its own expression engine; this handles basic cases only.
   */
  private evaluateExpression(expression: string, data: Record<string, unknown>): string {
    const match = expression.match(/\$\.json\.(\w+(?:\.\w+)*)\s*===\s*["'](\w+)["']\s*\?\s*["'](\w+)["']\s*:\s*["'](\w+)["']/);
    if (match) {
      const [, fieldPath, compareValue, trueValue, falseValue] = match;
      const fieldValue = this.getValueAtPath(data, fieldPath);
      return fieldValue === compareValue ? trueValue : falseValue;
    }
    return 'normal';
  }
}
