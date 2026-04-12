from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class Tramo:
    limite_inferior: float
    limite_superior: float
    tipo: float


TRAMOS_NACIONALES_2025 = [
    Tramo(0, 12450, 19.0),
    Tramo(12450, 20200, 24.0),
    Tramo(20200, 35200, 30.0),
    Tramo(35200, 60000, 37.0),
    Tramo(60000, 300000, 45.0),
    Tramo(300000, float('inf'), 47.0),
]

DEDUCCIONES_COMUNIDADES = {
    "AND": {
        "vivienda": 0.0,
        "alquiler": 0.0,
    },
    "MAD": {
        "vivienda": 0.0,
        "alquiler": 0.0,
    },
    "CAT": {
        "vivienda": 0.0,
        "alquiler": 0.0,
    },
    "GAL": {
        "vivienda": 0.0,
        "alquiler": 0.0,
    },
    "PVA": {
        "vivienda": 0.0,
        "alquiler": 0.0,
    },
    "CYL": {
        "vivienda": 0.0,
        "alquiler": 0.0,
    },
    "ARG": {
        "vivienda": 0.0,
        "alquiler": 0.0,
    },
}


MINIMO_VITAL = {
    "general": 5550.0,
    "por_hijo": 2400.0,
    "ascendiente": 1150.0,
    "discapacidad": 0.0,
}


def redondear(valor: float) -> float:
    return float(Decimal(str(valor)).quantize(Decimal('0.01'), ROUND_HALF_UP))


def calcular_base_imponible(datos: Dict[str, Any]) -> float:
    base = Decimal('0')
    
    ingresos_trabajo = datos.get("ingresos_trabajo", 0)
    base += Decimal(str(ingresos_trabajo))
    
    ingresos_pension = datos.get("ingresos_pension", 0)
    base += Decimal(str(ingresos_pension))
    
    ingresos_inmobiliarios = datos.get("ingresos_inmobiliarios", 0)
    base += Decimal(str(ingresos_inmobiliarios))
    
    ingresos_capital = datos.get("ingresos_capital", 0)
    base += Decimal(str(ingresos_capital))
    
    otros_ingresos = datos.get("otros_ingresos", 0)
    base += Decimal(str(otros_ingresos))
    
    reducciones = datos.get("reducciones", 0)
    base -= Decimal(str(reducciones))
    
    return max(0, float(base))


def calcular_cuota_tributaria(base_imponible: float, tranches: Optional[List[Tramo]] = None) -> Tuple[float, List[Dict[str, Any]]]:
    if tranches is None:
        tranches = TRAMOS_NACIONALES_2025
    
    cuota = Decimal('0')
    base_actual = base_imponible
    aplicados = []
    
    prev_limite = 0
    for i, tranche in enumerate(tranches):
        if base_actual <= 0:
            break
        
        base_gravable = min(base_imponible - prev_limite, tranche.limite_superior - prev_limite)
        base_gravable = max(0, base_gravable)
        
        if base_gravable > 0:
            cuota += Decimal(str(base_gravable)) * Decimal(str(tranche.tipo / 100))
            aplicados.append({
                "tramo": i + 1,
                "limite_inferior": prev_limite,
                "limite_superior": min(base_imponible, tranche.limite_superior),
                "tipo": tranche.tipo,
                "base_gravable": base_gravable,
                "cuota": float(cuota),
            })
            base_actual -= base_gravable
        
        prev_limite = tranches[i].limite_superior
    
    return float(cuota), aplicados


def calcular_deducciones(datos: Dict[str, Any], comunidad: str) -> Dict[str, float]:
    deducciones = {}
    
    deducciones["contribuciones_sistema_pension"] = datos.get("contribuciones_pension", 0)
    
    deducciones["donativos"] = datos.get("donativos", 0)
    
    deducciones["vivienda_habitual"] = datos.get("compra_vivienda", 0)
    
    edad = datos.get("edad", 0)
    if edad >= 65:
        deducciones["mayor_65"] = datos.get("renta_ahorrada", 0)
    
    hijos = datos.get("hijos_menores_25", 0)
    if hijos > 0:
        deducciones["hijos"] = hijos * 1200
    
    return deducciones


def calcular_minimo_personal(datos: Dict[str, Any]) -> float:
    minimo = MINIMO_VITAL["general"]
    
    hijos = datos.get("hijos_menores_25", 0)
    if hijos > 0:
        if datos.get("familia_numerosa", False):
            minimo += hijos * 2400
        else:
            minimo += hijos * 1200
    
    ascendientes = datos.get("ascendientes_mayores_65", 0)
    if ascendientes > 0:
        minimo += ascendientes * 1150
    
    return minimo


def calcular_resultado_irpf(datos: Dict[str, Any], es_conjoint: bool = False) -> Dict[str, Any]:
    base_imponible = calcular_base_imponible(datos)
    
    cuota_bruta, tramos_aplicados = calcular_cuota_tributaria(base_imponible)
    
    deducciones = calcular_deducciones(datos, datos.get("comunidad", "MAD"))
    deduccion_total = sum(deducciones.values())
    
    cuota_neta = max(0, cuota_bruta - deduccion_total)
    
    retenciones = datos.get("retenciones", 0)
    
    resultado = retenciones - cuota_neta
    
    tipo_medio = (cuota_neta / base_imponible * 100) if base_imponible > 0 else 0
    
    return {
        "base_imponible": redondear(base_imponible),
        "cuota_integral": redondear(cuota_bruta),
        "deducciones": {k: redondear(v) for k, v in deducciones.items()},
        "deduccion_total": redondear(deduccion_total),
        "cuota_neta": redondear(cuota_neta),
        "retenciones": redondear(retenciones),
        "resultado": redondear(resultado),
        "resultado_tipo": "a_pagar" if resultado < 0 else "a_devolver",
        "tramos_aplicados": tramos_aplicados,
        "tipo_medio": redondear(tipo_medio),
    }


def comparar_declaraciones(datos_persona1: Dict[str, Any], datos_persona2: Dict[str, Any]) -> Dict[str, Any]:
    resultado_individual1 = calcular_resultado_irpf(datos_persona1, False)
    resultado_individual2 = calcular_resultado_irpf(datos_persona2, False)
    
    total_individual = resultado_individual1["resultado"] + resultado_individual2["resultado"]
    
    datos_conjoint = {
        "ingresos_trabajo": datos_persona1.get("ingresos_trabajo", 0) + datos_persona2.get("ingresos_trabajo", 0),
        "ingresos_pension": datos_persona1.get("ingresos_pension", 0) + datos_persona2.get("ingresos_pension", 0),
        "ingresos_inmobiliarios": datos_persona1.get("ingresos_inmobiliarios", 0) + datos_persona2.get("ingresos_inmobiliarios", 0),
        "ingresos_capital": datos_persona1.get("ingresos_capital", 0) + datos_persona2.get("ingresos_capital", 0),
        "otros_ingresos": datos_persona1.get("otros_ingresos", 0) + datos_persona2.get("otros_ingresos", 0),
        "reducciones": datos_persona1.get("reducciones", 0) + datos_persona2.get("reducciones", 0),
        "retenciones": datos_persona1.get("retenciones", 0) + datos_persona2.get("retenciones", 0),
        "hijos_menores_25": datos_persona1.get("hijos_menores_25", 0) + datos_persona2.get("hijos_menores_25", 0),
        "donativos": datos_persona1.get("donativos", 0) + datos_persona2.get("donativos", 0),
    }
    
    resultado_conjoint = calcular_resultado_irpf(datos_conjoint, True)
    
    return {
        "individual": {
            "persona1": resultado_individual1,
            "persona2": resultado_individual2,
            "total": redondear(total_individual),
        },
        "conjoint": {
            "resultado": resultado_conjoint["resultado"],
            "base_imponible": resultado_conjoint["base_imponible"],
        },
        "recomendacion": "conjoint" if resultado_conjoint["resultado"] > total_individual else "individual",
        "ahorro": abs(resultado_conjoint["resultado"] - total_individual),
    }