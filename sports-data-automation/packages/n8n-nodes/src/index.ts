/**
 * packages/n8n-nodes/src/index.ts
 *
 * FILE HEADER
 * -----------
 * Business problem this file solves:
 *   n8n ships with generic nodes (HTTP Request, Code, Set, etc.) but nothing that understands
 *   sports-data concepts (odds formats, settlement rules, event routing priority, arbitrage).
 *   This file registers the four custom node types and the Sports API credential type so n8n
 *   can orchestrate the sports automation pipeline visually.
 *
 * Where it sits in the flow:
 *   Entry point of the n8n custom-nodes package. Imported by n8n at startup (via the
 *   "n8n.nodes" / "n8n.credentials" package.json fields) to register every node/credential.
 *   The nodes are the orchestration layer — they consume webhooks from the ingestion service
 *   and implement routing, normalization, settlement, and alerting.
 *
 * What calls it / what it calls:
 *   Called by: n8n runtime when loading the custom-nodes extension (packages/n8n-nodes/dist).
 *   Calls: imports each node class and the credentials class; re-exports them in the nodes /
 *     credentials arrays n8n expects.
 *
 * What breaks if removed:
 *   n8n won't register any of the custom nodes or credentials; the pipeline can only use
 *   generic nodes and can't express sports-specific logic.
 *
 * Language conventions:
 *   TypeScript (compiled to CommonJS). n8n expects `nodes` and `credentials` arrays exported
 *   from the entry point, and a "n8n" block in package.json listing the dist paths.
 */

// Entry point for n8n custom nodes
import { SportsEventRouter } from './Nodes/SportsEventRouter/SportsEventRouter.node';
import { OddsNormalizer } from './Nodes/OddsNormalizer/OddsNormalizer.node';
import { SettlementWorker } from './Nodes/SettlementWorker/SettlementWorker.node';
import { LLMAlertGenerator } from './Nodes/LLMAlertGenerator/LLMAlertGenerator.node';
import { SportsApiCredentials } from './credentials/SportsApiCredentials.credentials';

export const nodes = [
  SportsEventRouter,
  OddsNormalizer,
  SettlementWorker,
  LLMAlertGenerator,
];

export const credentials = [
  SportsApiCredentials,
];