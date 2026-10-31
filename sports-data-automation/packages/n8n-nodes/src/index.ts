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