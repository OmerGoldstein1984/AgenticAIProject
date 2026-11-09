/**
 * packages/n8n-nodes/src/credentials/SportsApiCredentials.credentials.ts
 *
 * FILE HEADER
 * -----------
 * Business problem this file solves:
 *   Each sports-data provider (LSports, Betradar, Sportradar, Custom) needs different auth
 *   (API key, secret, base URL, WebSocket URL, rate limit). n8n nodes that call provider APIs
 *   need a reusable, encrypted credential store so users don't paste secrets into node configs.
 *   This credential type defines the fields n8n collects (and encrypts at rest) once per
 *   provider connection.
 *
 * Where it sits in the flow:
 *   Authentication layer consumed by custom nodes when calling provider APIs. Registered
 *   alongside the nodes in index.ts.
 *
 * What calls it / what it calls:
 *   Called by: n8n credential UI (renders the fields) and by nodes that declare this
 *   credential type (access credentials via this.getCredentials()).
 *   Calls: nothing (pure declaration).
 *
 * What breaks if removed:
 *   Nodes that need provider auth have no place to store API keys/secrets; credentials would
 *   have to be hard-coded in node configs (a security anti-pattern).
 *
 * Language conventions:
 *   TypeScript. Implements n8n's ICredentialType; fields use typeOptions.password for secrets.
 */

import {
  ICredentialType,
  INodeProperties,
} from 'n8n-workflow';

export class SportsApiCredentials implements ICredentialType {
  /**
   * Internal credential name referenced by nodes.
   */
  name = 'sportsApiCredentials';
  /**
   * Human-readable label shown in the n8n credential picker.
   */
  displayName = 'Sports API Credentials';
  documentationUrl = 'https://docs.yourcompany.com/sports-api';
  properties: INodeProperties[] = [
    {
      displayName: 'Provider',
      name: 'provider',
      type: 'options',
      options: [
        { name: 'LSports', value: 'lsports' },
        { name: 'Betradar', value: 'betradar' },
        { name: 'Sportradar', value: 'sportradar' },
        { name: 'Custom', value: 'custom' },
      ],
      default: 'lsports',
    },
    {
      displayName: 'API Key',
      name: 'apiKey',
      type: 'string',
      typeOptions: { password: true },
      default: '',
      required: true,
    },
    {
      displayName: 'API Secret',
      name: 'apiSecret',
      type: 'string',
      typeOptions: { password: true },
      default: '',
    },
    {
      displayName: 'Base URL',
      name: 'baseUrl',
      type: 'string',
      default: 'https://api.lsports.com',
      description: 'Base URL for the API',
    },
    {
      displayName: 'WebSocket URL',
      name: 'wsUrl',
      type: 'string',
      default: 'wss://feed.lsports.com',
      description: 'WebSocket URL for live feeds',
    },
    {
      displayName: 'Rate Limit (req/s)',
      name: 'rateLimit',
      type: 'number',
      default: 100,
      description: 'Maximum requests per second',
    },
  ];
}
