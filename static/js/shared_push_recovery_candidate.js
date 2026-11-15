/* Loaded only by the isolated TESTING candidate template. No permission prompt. */
(function (root) {
    async function run(env) {
        if (env.permission !== 'granted') return {state: 'permission-required'};
        const nav = env.navigator;
        if (!nav.locks || !nav.serviceWorker || !env.expectedActor) {
            throw new Error('Shared push requires supported exclusive registration');
        }
        return nav.locks.request('dkss-shared-push-registration', async () => {
            async function context() {
                const response = await env.fetch('/api/push/vapid-public-key', {cache:'no-store'});
                if (!response.ok) throw new Error('Shared push context unavailable');
                const data = await response.json();
                if (!data.publicKey || !data.sharedContext || data.sharedActor !== env.expectedActor) {
                    throw new Error('Shared push viewer changed');
                }
                return data;
            }
            const initial = await context();
            const registration = await nav.serviceWorker.register('/service-worker.js');
            const manager = registration.pushManager;
            async function assertCurrent() {
                const current = await context();
                if (current.sharedContext !== initial.sharedContext) {
                    throw new Error('Shared push session changed');
                }
            }
            async function create() {
                await assertCurrent();
                return manager.subscribe({userVisibleOnly:true,
                    applicationServerKey:await env.keyBytes(initial.publicKey)});
            }
            async function save(subscription) {
                await assertCurrent();
                return env.fetch('/api/push/subscribe', {method:'POST',
                    headers:{'Content-Type':'application/json','X-CSRFToken':env.csrf},
                    body:JSON.stringify({...subscription.toJSON(), sharedContext:initial.sharedContext})});
            }
            let subscription = await manager.getSubscription();
            const existed = !!subscription;
            if (!subscription) subscription = await create();
            let response = await save(subscription);
            if (response.ok) return {state:'registered'};
            // Only an existing browser subscription gets one recovery attempt.
            if (response.status !== 409 || !existed) throw new Error('Shared push registration failed');
            await assertCurrent();
            if (!(await subscription.unsubscribe())) throw new Error('Shared push removal failed');
            await assertCurrent();
            // Never erase another account's server subscription or adopt its endpoint.
            if (await manager.getSubscription()) throw new Error('Shared push removal incomplete');
            const oldEndpoint = subscription.endpoint;
            subscription = await create();
            if (subscription.endpoint === oldEndpoint) throw new Error('Shared push endpoint was not rotated');
            response = await save(subscription);
            if (!response.ok) throw new Error('Shared push retry failed');
            return {state:'recovered'};
        });
    }
    root.DKSSSharedPushRecovery = {run};
})(typeof window === 'undefined' ? globalThis : window);
