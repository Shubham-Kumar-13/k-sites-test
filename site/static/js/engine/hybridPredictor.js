/**
 * Combines the optional hosted-LLM predictor with the free browser MiniLM predictor.
 * The hosted model is tried first when the user supplied a key; if it fails we fall back to MiniLM.
 */

import { LlmPhenotypePredictor } from './llmPredictor.js';

export class HybridPhenotypePredictor {
    constructor({ miniLmFactory, http, parseXml, ncbiApiKey, llmProvider, llmApiKey, onStatus }) {
        this.miniLmFactory = miniLmFactory;
        this.http = http;
        this.parseXml = parseXml;
        this.ncbiApiKey = ncbiApiKey;
        this.onStatus = onStatus;
        this.llmPredictor = llmApiKey ? new LlmPhenotypePredictor({ http, parseXml, provider: llmProvider, apiKey: llmApiKey, ncbiApiKey }) : null;
        this.miniLmPredictor = null;
        this.llmError = null;
    }

    async predict(symbol, taxid, includeCompensatory, aliases) {
        if (this.llmPredictor && !this.llmError) {
            try {
                return await this.llmPredictor.predict(symbol, taxid, includeCompensatory, aliases);
            } catch (error) {
                this.llmError = error.message || 'LLM API failed';
            }
        }

        if (!this.miniLmPredictor) {
            if (this.onStatus) {
                this.onStatus(this.llmError
                    ? `LLM API failed (${this.llmError}); loading free browser model`
                    : 'Loading the phenotype model (about 90 MB, downloaded once)');
            }
            this.miniLmPredictor = await this.miniLmFactory();
        }

        const prediction = await this.miniLmPredictor.predict(symbol, taxid, includeCompensatory, aliases);
        if (this.llmError) {
            prediction.confidence_reasoning = `LLM API failed (${this.llmError}); falling back to the free browser model. ${prediction.confidence_reasoning || ''}`;
        }
        return prediction;
    }
}
