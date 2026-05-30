import requests


class DroughtLLMExplainer:
    def __init__(self, ollama_url='http://localhost:11434', model_name='llama3.2:3b'):
        self.ollama_url = ollama_url
        self.model_name = model_name
        self.available = self._check_availability()

    def _check_availability(self):
        try:
            response = requests.get(f'{self.ollama_url}/api/tags', timeout=5)
            if response.status_code == 200:
                models = response.json().get('models', [])
                return any(self.model_name in model.get('name', '') for model in models)
            return False
        except Exception:
            return False

    def generate_explanation(self, risk_today, risk_7day, risk_30day, drivers, soil_moisture_pct, awc_mm):
        if not self.available:
            return self._fallback_explanation(risk_today, drivers)

        soil_pct_of_capacity = int((soil_moisture_pct / awc_mm) * 100) if awc_mm > 0 else 50

        def risk_level(score):
            if score <= 20:
                return 'Normal'
            if score <= 40:
                return 'Watch'
            if score <= 60:
                return 'Moderate'
            if score <= 80:
                return 'Severe'
            return 'Extreme'

        prompt = f"""You are a drought analysis assistant for Ichkeul Lake, Tunisia.
Generate a 2-3 sentence explanation for a farmer or park manager based on these data:

- Current drought risk: {risk_today}/100 ({risk_level(risk_today)})
- Forecast risk in 7 days: {risk_7day}/100 ({risk_level(risk_7day)})
- Forecast risk in 30 days: {risk_30day}/100 ({risk_level(risk_30day)})
- Primary driver: {drivers.get('rainfall_deficit', 0)}% rainfall deficit
- Secondary driver: {drivers.get('high_temperature', 0)}% temperature anomaly
- Current soil moisture: {soil_moisture_pct}% ({soil_pct_of_capacity}% of available capacity)

Write a concise, actionable explanation (2-3 sentences) that explains the current situation, the near-term trend, and one specific action. Do not use markdown, bullet points, or numbered lists."""

        try:
            response = requests.post(
                f'{self.ollama_url}/api/generate',
                json={
                    'model': self.model_name,
                    'prompt': prompt,
                    'stream': False,
                    'temperature': 0.5,
                    'max_tokens': 250,
                },
                timeout=30,
            )
            if response.status_code == 200:
                return response.json().get('response', '').strip()
            return self._fallback_explanation(risk_today, drivers)
        except Exception:
            return self._fallback_explanation(risk_today, drivers)

    def _fallback_explanation(self, risk_today, drivers):
        rainfall_deficit = drivers.get('rainfall_deficit', 0)

        if risk_today <= 20:
            return f'Conditions are normal with a {rainfall_deficit}% rainfall deficit within seasonal variation. Continue routine monitoring of soil moisture and vegetation health.'
        if risk_today <= 40:
            return f'The current drought risk is moderate (Watch level), driven by a {rainfall_deficit}% rainfall deficit. Prepare irrigation systems for potential use within the next 10-14 days.'
        if risk_today <= 60:
            return f'Moderate drought risk with {rainfall_deficit}% rainfall deficit and elevated temperatures. Begin water restrictions for non-essential crops and monitor soil moisture twice weekly.'
        if risk_today <= 80:
            return f'Severe drought risk detected. Rainfall deficit of {rainfall_deficit}% and declining soil moisture require immediate action. Start irrigation for critical crops and reduce non-essential water use.'
        return f'EXTREME DROUGHT EMERGENCY. {rainfall_deficit}% rainfall deficit and critical soil moisture levels. Activate emergency water protocols and cease all non-essential water usage immediately.'