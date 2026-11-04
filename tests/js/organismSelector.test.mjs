import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { parseHTML } from 'linkedom';
import { ROOT } from './helpers.mjs';

const source = fs.readFileSync(`${ROOT}/webapp/static/js/main.js`, 'utf8');
const ids = [
    'kingdomContainer', 'speciesSection', 'selectedKingdomName', 'speciesSearch', 'speciesList',
    'selectedOrganismDisplay', 'selectedOrganismName', 'selectedOrganismTaxid', 'organismDirectSection',
    'organismDirectSearch', 'organismDirectResults', 'evidenceCoverageNote', 'organism', 'taxid',
];

function setup() {
    const { document, window } = parseHTML(`<html><body>${ids.map((id) => `<div id="${id}"></div>`).join('')}</body></html>`);
    document.getElementById('speciesSearch').focus = () => {};
    const context = vm.createContext({
        window, document, console, encodeURIComponent,
        ksFetch: async () => ({ json: async () => ({ results: [] }) }),
        showEvidenceCoverage: () => {}, checkGeneCount: () => {},
    });
    vm.runInContext(source, context);
    vm.runInContext('showEvidenceCoverage = () => {}; checkGeneCount = () => {};', context);
    return { context, document };
}

const options = [
    { name: 'Animals', icon: 'fa-paw', description: 'Animals' },
    { name: 'Plants', icon: 'fa-leaf', description: 'Plants' },
    { name: 'Microbes', icon: 'fa-bacterium', description: 'Microbes' },
    { name: 'Fungi', icon: 'fa-mushroom', description: 'Fungi', svg: '<path d="M0 0h10v10z"/>' },
    { name: 'Other Eukaryotes', icon: 'fa-dna', description: 'Other' },
];

test('Fungi renders a visible SVG icon', () => {
    const { context, document } = setup();
    context.options = options;
    vm.runInContext('renderKingdoms(options)', context);

    const fungi = document.querySelector('[data-kingdom="Fungi"]');
    assert.ok(fungi.innerHTML.includes('<svg'));
    assert.ok(fungi.innerHTML.includes('<path'));
});

test('selecting a category never replaces its icon with a permanent loading spinner', async () => {
    const { context, document } = setup();
    context.options = options;
    vm.runInContext('renderKingdoms(options)', context);

    await vm.runInContext("selectKingdom('Animals')", context);

    const animals = document.querySelector('[data-kingdom="Animals"]');
    assert.ok(animals.innerHTML.includes('fa-paw'));
    assert.ok(!animals.innerHTML.includes('Loading Animals'));
});

test('Change organism returns to the species list in the same category', async () => {
    const { context, document } = setup();
    context.options = options;
    vm.runInContext("renderKingdoms(options); selectedKingdom = 'Animals'; selectedOrganism = { name: 'Acanthisitta chloris' };", context);

    await vm.runInContext('resetOrganismSelection()', context);

    assert.equal(vm.runInContext('selectedKingdom', context), 'Animals');
    assert.equal(vm.runInContext('selectedOrganism', context), null);
    assert.equal(document.getElementById('speciesSection').style.display, 'block');
    assert.equal(document.getElementById('kingdomContainer').style.display, 'none');
});

test('Change category restores all cards and direct selection clears the old category', async () => {
    const { context, document } = setup();
    context.options = options;
    vm.runInContext('renderKingdoms(options)', context);
    await vm.runInContext("selectKingdom('Animals')", context);

    vm.runInContext('resetKingdomSelection()', context);

    assert.equal(vm.runInContext('selectedKingdom', context), null);
    assert.equal(document.querySelectorAll('.kingdom-card').length, 5);
    assert.ok(!document.getElementById('kingdomContainer').innerHTML.includes('Loading Animals'));
    vm.runInContext("selectedKingdom = 'Animals'; selectOrganism('Example species', '1', '', false)", context);
    assert.equal(vm.runInContext('selectedKingdom', context), null);
});
