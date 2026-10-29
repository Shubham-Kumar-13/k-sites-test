/**
 * Combines the optional Kimi LLM predictor with the free browser MiniLM predictor.
 * Kimi is tried first when the user supplied a key; if it fails we fall back to MiniLM.
 */

import { KimiPhenotypePredictor } from './kimiPredictor.js';

export class HybridPhenotypePredictor {
    constructor({ miniLmFactory, http, parseXml, ncbiApiKey, kimiApiKey, onStatus }) {
        this.miniLmFactory = miniLmFactory;
        this.http = http;
        this.parseXml = parseXml;
        this.ncbiApiKey = ncbiApiKey;
        this.onStatus = onStatus;
        this.kimiPredictor = kimiApiKey ? new KimiPhenotypePredictor({ http, parseXml, apiKey: kimiApiKey, ncbiApiKey }) : null;
        this.miniLmPredictor = null;
        this.kimiError = null;
    }

    async predict(symbol, taxid, includeCompensatory, aliases) {
        if (this.kimiPredictor && !this.kimiError) {
            try {
                return await this.kimiPredictor.predict(symbol, taxid, includeCompensatory, aliases);
            } catch (error) {
                this.kimiError = error.message || 'Kimi API failed';
            }
        }

        if (!this.miniLmPredictor) {
            if (this.onStatus) {
                this.onStatus(this.kimiError
                    ? `Kimi API failed (${this.kimiError}); loading free browser model`
                    : 'Loading the phenotype model (about 90 MB, downloaded once)');
            }
            this.miniLmPredictor = await this.miniLmFactory();
        }

        const prediction = await this.miniLmPredictor.predict(symbol, taxid, includeCompensatory, aliases);
        if (this.kimiError) {
            prediction.confidence_reasoning = `Kimi API failed (${this.kimiError}); falling back to the free browser model. ${prediction.confidence_reasoning || ''}`;
        }
        return prediction;
    }
}
