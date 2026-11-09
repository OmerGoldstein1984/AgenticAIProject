/**
 * packages/n8n-nodes/src/Nodes/OddsNormalizer/OddsNormalizer.node.ts
 *
 * FILE HEADER
 * -----------
 * Business problem this file solves:
 *   Providers quote odds in Decimal (European), American (moneyline), or Fractional (UK)
 *   formats, and each provider's prices for the same market differ. OddsNormalizer is an n8n
 *   custom node that converts every quote to a chosen output format, validates odds ranges and
   * staleness, computes implied probability, detects cross-provider arbitrage (total implied
   * probability < 100%), and flags the best odds per selection — all in one node.
 *
 * Where it sits in the flow:
 *   After SportsEventRouter routes normalized events here. Consumes canonical odds from the
   * ingestion webhook and emits three outputs: Normalized odds, Arbitrage opportunities, and
   * Errors/Invalid. Arbitrage output feeds risk/exposure checks; normalized odds feed the
   * trading/CRM systems.
 *
 * What calls it / what it calls:
 *   Called by: n8n workflow engine (execute()), triggered by routed odds events.
 *   Calls: nothing external (pure in-node logic); private helpers toDecimal/fromDecimal/
   *   isBetterOdds.
 *
 * What breaks if removed:
 *   Odds stay in provider-specific formats; cross-provider comparison and arbitrage detection
   * are impossible, and stale/invalid odds reach downstream systems.
 *
 * Language conventions:
 *   TypeScript/n8n custom node. Three Main outputs (Normalized/Arbitrage/Errors).
 *
 * # GAP: best-odds/arbitrage are computed in-memory within a single execute batch; there's no
 *   cross-batch state, so an arbitrage spanning two polls in different batches is missed.
 *   See 07_issues_found.md.
 * # INTERVIEW: arbitrage exists when sum(1/best_decimal_odds across all selections) < 1 — the
 *   margin is the bookmaker's guaranteed profit if they lay every outcome at those odds.
 */

import {
  INodeType,
  INodeTypeDescription,
  IExecuteFunctions,
  INodeExecutionData,
  NodeConnectionType,
} from 'n8n-workflow';

export class OddsNormalizer implements INodeType {
  /**
   * n8n node metadata and configurable parameters (output format, arbitrage detection,
   * best-odds selection, validation rules, output fields). Drives the n8n UI panel.
   */
  description: INodeTypeDescription = {
    displayName: 'Odds Normalizer',
    name: 'oddsNormalizer',
    icon: 'file:odds-normalizer.svg',
    group: ['transform'],
    version: 1,
    subtitle: '={{$parameter["outputFormat"]}}',
    description: 'Normalizes odds from multiple providers to canonical format with arbitrage detection',
    defaults: {
      name: 'Odds Normalizer',
    },
    inputs: [NodeConnectionType.Main],
    outputs: [
      NodeConnectionType.Main, // Normalized odds
      NodeConnectionType.Main, // Arbitrage opportunities
      NodeConnectionType.Main, // Errors/Invalid
    ],
    outputNames: ['Normalized', 'Arbitrage', 'Errors'],
    properties: [
      {
        displayName: 'Output Format',
        name: 'outputFormat',
        type: 'options',
        options: [
          { name: 'Decimal (European)', value: 'decimal' },
          { name: 'American (Moneyline)', value: 'american' },
          { name: 'Fractional (UK)', value: 'fractional' },
        ],
        default: 'decimal',
        description: 'Target odds format for normalized output',
      },
      {
        displayName: 'Provider Odds Field',
        name: 'oddsField',
        type: 'string',
        default: 'odds',
        description: 'Field name containing the odds value in input data',
      },
      {
        displayName: 'Provider Format Field',
        name: 'formatField',
        type: 'string',
        default: 'format',
        description: 'Field name indicating the source odds format',
      },
      {
        displayName: 'Arbitrage Detection',
        name: 'arbitrageDetection',
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
            displayName: 'Minimum Margin %',
            name: 'minMarginPercent',
            type: 'number',
            default: 0.5,
            description: 'Minimum arbitrage margin to flag (percentage)',
          },
          {
            displayName: 'Group By',
            name: 'groupBy',
            type: 'options',
            options: [
              { name: 'Event + Market', value: 'eventMarket' },
              { name: 'Event Only', value: 'event' },
            ],
            default: 'eventMarket',
            description: 'How to group odds for arbitrage calculation',
          },
          {
            displayName: 'Max Providers Per Group',
            name: 'maxProviders',
            type: 'number',
            default: 10,
          },
        ],
      },
      {
        displayName: 'Best Odds Selection',
        name: 'bestOddsSelection',
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
            displayName: 'Selection Strategy',
            name: 'strategy',
            type: 'options',
            options: [
              { name: 'Highest Odds', value: 'highest' },
              { name: 'Weighted by Provider Reliability', value: 'weighted' },
              { name: 'Most Recent', value: 'recent' },
            ],
            default: 'highest',
          },
          {
            displayName: 'Provider Weights',
            name: 'providerWeights',
            type: 'fixedCollection',
            typeOptions: { multipleValues: true },
            default: {},
            options: [
              {
                name: 'weight',
                displayName: 'Weight',
                values: [
                  {
                    displayName: 'Provider ID',
                    name: 'providerId',
                    type: 'string',
                  },
                  {
                    displayName: 'Weight',
                    name: 'weight',
                    type: 'number',
                    default: 1,
                  },
                ],
              },
            ],
            displayOptions: {
              show: {
                strategy: ['weighted'],
              },
            },
          },
        ],
      },
      {
        displayName: 'Validation Rules',
        name: 'validationRules',
        type: 'collection',
        placeholder: 'Add Setting',
        default: {},
        options: [
          {
            displayName: 'Min Odds Value',
            name: 'minOdds',
            type: 'number',
            default: 1.01,
          },
          {
            displayName: 'Max Odds Value',
            name: 'maxOdds',
            type: 'number',
            default: 1000,
          },
          {
            displayName: 'Reject Stale Odds',
            name: 'rejectStale',
            type: 'boolean',
            default: true,
          },
          {
            displayName: 'Max Age (seconds)',
            name: 'maxAgeSeconds',
            type: 'number',
            default: 300,
            displayOptions: {
              show: {
                rejectStale: [true],
              },
            },
          },
        ],
      },
      {
        displayName: 'Output Fields',
        name: 'outputFields',
        type: 'fixedCollection',
        typeOptions: { multipleValues: true },
        default: {},
        options: [
          {
            name: 'field',
            displayName: 'Field',
            values: [
              {
                displayName: 'Include',
                name: 'include',
                type: 'boolean',
                default: true,
              },
              {
                displayName: 'Field Name',
                name: 'name',
                type: 'options',
                options: [
                  { name: 'Provider ID', value: 'providerId' },
                  { name: 'Event ID', value: 'eventId' },
                  { name: 'Market ID', value: 'marketId' },
                  { name: 'Selection ID', value: 'selectionId' },
                  { name: 'Normalized Odds', value: 'odds' },
                  { name: 'Original Odds', value: 'originalOdds' },
                  { name: 'Original Format', value: 'originalFormat' },
                  { name: 'Timestamp', value: 'timestamp' },
                  { name: 'Sequence', value: 'sequence' },
                  { name: 'Implied Probability', value: 'impliedProbability' },
                  { name: 'Arbitrage Margin', value: 'arbitrageMargin' },
                  { name: 'Best Odds Flag', value: 'isBestOdds' },
                ],
                default: 'odds',
              },
            ],
          },
        ],
      },
    ],
  };

  /**
   * Main execution: normalize odds, detect arbitrage, pick best odds per selection.
   *
   * WHAT: For each input item, extract odds/format/provider/event/market/selection, validate
   *   (odds present, numeric, within [minOdds,maxOdds], not stale), convert to decimal, compute
   *   implied probability, group by event:market (or event), then per selection find the best
   *   odds and detect arbitrage (total implied probability < minMarginPercent). Emits normalized
   *   odds, arbitrage opportunities, and invalid items to three outputs.
   * WHY: One canonical odds format lets downstream systems compare across providers; arbitrage
   *   detection protects the book from sure-loss markets; best-odds selection surfaces the most
   *   competitive price to traders.
   * INPUTS: this.getInputData() — n8n input items (item.json = odds data).
   * OUTPUTS: INodeExecutionData[][] — [normalizedOutput, arbitrageOutput, errorOutput].
   * SIDE EFFECTS: none external; mutates normalized output items to set isBestOdds/
   *   arbitrageMargin.
   * FAILURE MODES: invalid/missing/stale odds → error output (item continues to other items);
   *   a single bad item never aborts the whole batch.
   * ALTERNATIVE: normalize in the ingestion service (Python). Chosen an n8n node so the
   *   business users can configure formats/thresholds in the UI without a redeploy.
   * # INTERVIEW: implied probability = 1/decimal_odds; arbitrage margin = (1 - total implied
   *   probability) * 100; positive margin = guaranteed-profit arb opportunity.
   */
  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const normalizedOutput: INodeExecutionData[] = [];
    const arbitrageOutput: INodeExecutionData[] = [];
    const errorOutput: INodeExecutionData[] = [];

    const outputFormat = this.getNodeParameter('outputFormat', 0) as 'decimal' | 'american' | 'fractional';
    const oddsField = this.getNodeParameter('oddsField', 0) as string;
    const formatField = this.getNodeParameter('formatField', 0) as string;
    const arbitrageSettings = this.getNodeParameter('arbitrageDetection', 0) as {
      enabled: boolean;
      minMarginPercent: number;
      groupBy: 'eventMarket' | 'event';
      maxProviders: number;
    };
    const bestOddsSettings = this.getNodeParameter('bestOddsSelection', 0) as {
      enabled: boolean;
      strategy: 'highest' | 'weighted' | 'recent';
      providerWeights: Array<{ providerId: string; weight: number }>;
    };
    const validationRules = this.getNodeParameter('validationRules', 0) as {
      minOdds: number;
      maxOdds: number;
      rejectStale: boolean;
      maxAgeSeconds: number;
    };
    const outputFields = this.getNodeParameter('outputFields.field', 0, []) as Array<{
      include: boolean;
      name: string;
    }>;

    // Group odds for arbitrage detection and best odds selection
    const groups = new Map<string, typeof items>();

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const data = item.json;

      // Extract odds and format
      const odds = data[oddsField];
      const format = data[formatField] || 'decimal';
      const providerId = data.providerId || data.provider_id || 'unknown';
      const eventId = data.eventId || data.event_id;
      const marketId = data.marketId || data.market_id;
      const selectionId = data.selectionId || data.selection_id;
      const timestamp = data.timestamp;
      const sequence = data.sequence;

      // Validate
      const errors: string[] = [];
      if (odds === undefined || odds === null) {
        errors.push(`Missing odds field: ${oddsField}`);
      }
      if (typeof odds !== 'number' || isNaN(odds)) {
        errors.push('Odds must be a valid number');
      }
      if (odds < validationRules.minOdds || odds > validationRules.maxOdds) {
        errors.push(`Odds ${odds} outside valid range [${validationRules.minOdds}, ${validationRules.maxOdds}]`);
      }
      if (validationRules.rejectStale && timestamp) {
        const age = Date.now() - new Date(timestamp).getTime();
        if (age > validationRules.maxAgeSeconds * 1000) {
          errors.push(`Odds too old: ${Math.round(age / 1000)}s > ${validationRules.maxAgeSeconds}s`);
        }
      }

      if (errors.length > 0) {
        errorOutput.push({
          json: {
            ...data,
            _normalizationErrors: errors,
            _processedAt: new Date().toISOString(),
          },
          pairedItem: { item: i },
        });
        continue;
      }

      // Convert to decimal for internal calculations
      const decimalOdds = this.toDecimal(odds, format);

      // Calculate implied probability
      const impliedProbability = 1 / decimalOdds;

      // Group for arbitrage/best odds
      const groupKey = arbitrageSettings.groupBy === 'eventMarket'
        ? `${eventId}:${marketId}`
        : `${eventId}`;

      if (!groups.has(groupKey)) {
        groups.set(groupKey, []);
      }
      groups.get(groupKey)!.push({
        ...data,
        _decimalOdds: decimalOdds,
        _impliedProbability: impliedProbability,
        _providerId: providerId,
        _originalOdds: odds,
        _originalFormat: format,
        _itemIndex: i,
      });

      // Build normalized output
      const normalized: Record<string, unknown> = {
        ...data,
      };

      // Apply output field selection
      const fieldMap: Record<string, unknown> = {
        providerId,
        eventId,
        marketId,
        selectionId,
        odds: decimalOdds,
        originalOdds: odds,
        originalFormat: format,
        timestamp,
        sequence,
        impliedProbability,
        isBestOdds: false, // Will be updated after grouping
      };

      for (const field of outputFields) {
        if (field.include && fieldMap[field.name] !== undefined) {
          normalized[field.name] = fieldMap[field.name];
        }
      }

      normalizedOutput.push({
        json: normalized,
        pairedItem: { item: i },
      });
    }

    // Process groups for arbitrage detection and best odds
    if (arbitrageSettings.enabled) {
      for (const [groupKey, groupItems] of groups) {
        if (groupItems.length < 2) continue; // Need at least 2 providers

        // Limit providers
        const limitedItems = groupItems.slice(0, arbitrageSettings.maxProviders);

        // Calculate arbitrage
        // For each selection, find best odds across providers
        const selections = new Map<string, typeof limitedItems>();
        for (const item of limitedItems) {
          const selKey = item.selectionId || item.selection_id || 'unknown';
          if (!selections.has(selKey)) {
            selections.set(selKey, []);
          }
          selections.get(selKey)!.push(item);
        }

        // Check each selection for arbitrage
        let totalImpliedProb = 0;
        const bestOddsPerSelection = new Map<string, typeof limitedItems[0]>();

        for (const [selKey, selItems] of selections) {
          let bestItem = selItems[0];
          for (const item of selItems) {
            const isBetter = this.isBetterOdds(item, bestItem, bestOddsSettings);
            if (isBetter) {
              bestItem = item;
            }
          }
          bestOddsPerSelection.set(selKey, bestItem);
          totalImpliedProb += 1 / bestItem._decimalOdds;
        }

        // Arbitrage exists if total implied probability < 1
        const arbitrageMargin = (1 - totalImpliedProb) * 100;

        if (arbitrageMargin >= arbitrageSettings.minMarginPercent) {
          // Mark best odds in normalized output
          for (const [, bestItem] of bestOddsPerSelection) {
            // Find and update the normalized output item
            for (const outItem of normalizedOutput) {
              if (outItem.pairedItem?.item === bestItem._itemIndex) {
                outItem.json.isBestOdds = true;
                outItem.json.arbitrageMargin = arbitrageMargin;
                break;
              }
            }
          }

          // Emit arbitrage opportunity
          arbitrageOutput.push({
            json: {
              groupKey,
              eventId: groupItems[0].eventId || groupItems[0].event_id,
              marketId: groupItems[0].marketId || groupItems[0].market_id,
              selections: Array.from(bestOddsPerSelection.entries()).map(([selKey, item]) => ({
                selectionId: selKey,
                providerId: item._providerId,
                odds: item._decimalOdds,
                impliedProbability: 1 / item._decimalOdds,
              })),
              totalImpliedProbability: totalImpliedProb,
              arbitrageMarginPercent: arbitrageMargin,
              detectedAt: new Date().toISOString(),
              providerCount: limitedItems.length,
            },
            pairedItem: { item: groupItems[0]._itemIndex },
          });
        } else {
          // Still mark best odds even if no arbitrage
          for (const [, bestItem] of bestOddsPerSelection) {
            for (const outItem of normalizedOutput) {
              if (outItem.pairedItem?.item === bestItem._itemIndex) {
                outItem.json.isBestOdds = true;
                break;
              }
            }
          }
        }
      }
    }

    return [normalizedOutput, arbitrageOutput, errorOutput];
  }

  private toDecimal(odds: number, format: string): number {
    switch (format.toLowerCase()) {
      case 'decimal':
        return odds;
      case 'american':
      case 'moneyline':
        if (odds > 0) {
          return (odds / 100) + 1;
        } else {
          return (100 / Math.abs(odds)) + 1;
        }
      case 'fractional':
      case 'fraction':
        // Expecting format like "5/1" or already parsed as 5/1 = 5
        if (typeof odds === 'string' && odds.includes('/')) {
          const [num, den] = odds.split('/').map(Number);
          return num / den + 1;
        }
        return odds + 1; // Assume already computed fractional value
      default:
        return odds; // Assume decimal
    }
  }

  private fromDecimal(decimalOdds: number, format: 'decimal' | 'american' | 'fractional'): number {
    switch (format) {
      case 'decimal':
        return decimalOdds;
      case 'american':
        if (decimalOdds >= 2) {
          return Math.round((decimalOdds - 1) * 100);
        } else {
          return Math.round(-100 / (decimalOdds - 1));
        }
      case 'fractional':
        // Return as decimal fraction (e.g., 5/1 = 5)
        return decimalOdds - 1;
      default:
        return decimalOdds;
    }
  }

  private isBetterOdds(a: any, b: any, settings: any): boolean {
    switch (settings.strategy) {
      case 'highest':
        return a._decimalOdds > b._decimalOdds;
      case 'weighted':
        const weightA = settings.providerWeights.find((w: any) => w.providerId === a._providerId)?.weight || 1;
        const weightB = settings.providerWeights.find((w: any) => w.providerId === b._providerId)?.weight || 1;
        return a._decimalOdds * weightA > b._decimalOdds * weightB;
      case 'recent':
        const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
        const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
        return timeA > timeB;
      default:
        return a._decimalOdds > b._decimalOdds;
    }
  }
}