import {
  ICredentialType,
  INodeProperties,
} from 'n8n-workflow';

export class SportsApiCredentials implements ICredentialType {
  name = 'sportsApiCredentials';
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