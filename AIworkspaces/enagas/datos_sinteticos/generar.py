"""
Generador de datos sintéticos que imitan las 5 fuentes del reto Enagás.

Crea en datos_sinteticos/salida/:
  um.csv             maestro de Unidades de Medida (tipo Energía/Volumen, ramal, cromatógrafo...)
  neptuno.csv        lecturas diarias de campo (volumen normalizado, PCS calculado, energía, estado)
  slm.csv            consumos calculados CON las modificaciones/ajustes de los usuarios
  orion.csv          consumos validados por el GTS
  calidad_gas.csv    PCS diario de cada cromatógrafo
  contrastacion.csv  contrastaciones de contadores (error %, observaciones)
  etiquetas.csv      incidencias REALES inyectadas (solo existe en sintético, para evaluar)

Mezcla dos cosas:
  - INCIDENCIAS reales (fallo de comunicación, deriva del conversor, pico de lectura, PCS erróneo,
    contador bloqueado) que el usuario suele corregir después con un ajuste → etiqueta para el modelo.
  - COMPORTAMIENTOS NORMALES que las reglas estándar marcan por error: centrales de ciclo combinado
    que arrancan y paran, UM pequeñas con ruido relativo alto, desfase sistemático conocido con ORION,
    olas de frío, paradas de agosto en industria, UM que siempre llegan moduladas...

Ejecutar:  python datos_sinteticos/generar.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEMILLA = 7
FECHA_INI, FECHA_FIN = "2024-01-01", "2025-06-30"
N_UM = 120
N_RAMALES = 12
SALIDA = Path(__file__).resolve().parent / "salida"
rng = np.random.default_rng(SEMILLA)

ZONAS = ["Norte", "Centro", "Levante", "Sur", "Noroeste", "Ebro"]
OLAS_FRIO = [("2024-01-15", "2024-01-22"), ("2025-01-08", "2025-01-14")]
PARADA_INDUSTRIAL = [("2024-08-05", "2024-08-18"), ("2024-12-24", "2025-01-01")]
FESTIVOS = ["2024-01-01", "2024-01-06", "2024-03-29", "2024-05-01", "2024-08-15", "2024-10-12",
            "2024-11-01", "2024-12-06", "2024-12-25", "2025-01-01", "2025-01-06", "2025-04-18", "2025-05-01"]

TIPOS_INCIDENCIA = {  # tipo: (probabilidad, duración min, duración max, prob. de que el usuario lo corrija)
    "fallo_comunicacion": (0.30, 1, 3, 0.90),
    "deriva_conversor": (0.15, 15, 40, 0.85),
    "pico_lectura": (0.20, 1, 1, 0.95),
    "pcs_erroneo": (0.15, 2, 7, 0.85),
    "contador_bloqueado": (0.20, 2, 8, 0.90),
}
AJUSTE_POR_TIPO = {
    "fallo_comunicacion": "Sustitución por estimación",
    "deriva_conversor": "Corrección lectura conversor",
    "pico_lectura": "Corrección lectura",
    "pcs_erroneo": "Corrección PCS",
    "contador_bloqueado": "Sustitución por ORION",
}


def generar_um() -> pd.DataFrame:
    filas = []
    for i in range(N_UM):
        ramal = i % N_RAMALES
        tipo_consumo = rng.choice(["distribucion", "industrial", "ccgt"], p=[0.5, 0.35, 0.15])
        base = {"distribucion": 40000, "industrial": 20000, "ccgt": 150000}[tipo_consumo]
        base *= rng.lognormal(0, 0.6)
        if rng.random() < 0.15:          # UM pequeñas: el ruido relativo con ORION es alto (normal para ellas)
            base = rng.uniform(1500, 3000)
        filas.append({
            "um_id": f"UM{i + 1:03d}",
            "tipo_um": "Energia" if rng.random() < 0.7 else "Volumen",
            "tipo_consumo": tipo_consumo,
            "ramal": f"RAMAL-{ramal + 1:02d}",
            "zona": ZONAS[ramal // 2],
            "cromatografo_id": f"CR{ramal // 2 + 1}",
            "volumen_base": round(base, 0),
            # comportamientos "raros pero normales" de cada UM (las reglas estándar los marcan siempre)
            "desfase_orion": rng.choice([0.0, rng.uniform(0.008, 0.015) * rng.choice([-1, 1])], p=[0.8, 0.2]),
            "modula_habitual": rng.random() < 0.10,
            "serie_habitual": rng.random() < 0.08,
        })
    return pd.DataFrame(filas)


def temperatura(fechas: pd.DatetimeIndex) -> np.ndarray:
    doy = fechas.day_of_year.values
    t = 15 - 9 * np.cos(2 * np.pi * (doy - 15) / 365) + rng.normal(0, 2, len(fechas))
    for ini, fin in OLAS_FRIO:
        t[(fechas >= ini) & (fechas <= fin)] -= 7
    return t


def pcs_cromatografos(fechas) -> pd.DataFrame:
    filas = []
    doy = fechas.day_of_year.values
    for c in range(len(ZONAS)):
        fase = rng.uniform(0, 2 * np.pi)
        pcs = 11.55 + 0.12 * np.sin(2 * np.pi * doy / 365 + fase) + np.cumsum(rng.normal(0, 0.004, len(fechas)))
        pcs = np.clip(pcs, 11.2, 11.95)
        filas.append(pd.DataFrame({"cromatografo_id": f"CR{c + 1}", "fecha": fechas, "pcs": pcs.round(4)}))
    return pd.concat(filas, ignore_index=True)


def volumen_real(u, fechas, hdd) -> np.ndarray:
    n = len(fechas)
    dow = fechas.day_of_week.values
    base = u.volumen_base
    if u.tipo_consumo == "distribucion":
        v = base * (0.35 + 0.065 * hdd) * np.where(dow >= 5, 0.95, 1.0) * rng.lognormal(0, 0.04, n)
    elif u.tipo_consumo == "industrial":
        v = base * (0.9 + 0.01 * hdd) * np.select([dow == 5, dow == 6], [0.55, 0.30], 1.0) * rng.lognormal(0, 0.05, n)
        festivo = fechas.strftime("%Y-%m-%d").isin(FESTIVOS)
        v[festivo] *= 0.35
        for ini, fin in PARADA_INDUSTRIAL:
            v[(fechas >= ini) & (fechas <= fin)] *= 0.15
    else:  # ccgt: arranca y para según el mercado eléctrico
        enc = np.zeros(n, dtype=bool)
        estado = True
        for i in range(n):
            if rng.random() < 0.12:
                estado = not estado
            enc[i] = estado
        v = np.where(enc, base * rng.uniform(0.5, 1.0, n), base * 0.01 * rng.random(n))
    return v


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    fechas = pd.date_range(FECHA_INI, FECHA_FIN, freq="D")
    n = len(fechas)
    ums = generar_um()
    temp = temperatura(fechas)
    cal = pcs_cromatografos(fechas)
    pcs_por_crom = {c: g["pcs"].values for c, g in cal.groupby("cromatografo_id")}

    neptuno, slm, orion, contrastes, etiquetas = [], [], [], [], []
    for u in ums.itertuples():
        hdd = np.maximum(0, 17 - (temp + rng.normal(0, 1, n)))
        v_real = volumen_real(u, fechas, hdd)
        pcs_crom = pcs_por_crom[u.cromatografo_id]

        # --- ORION: referencia del GTS (ruido relativo + absoluto, y desfase sistemático en algunas UM)
        o_vol = v_real * (1 + u.desfase_orion) * rng.normal(1, 0.002, n) + rng.normal(0, 30, n)
        o_ene = o_vol * pcs_crom

        # --- Neptuno: lo que llega del campo (sin incidencias de momento)
        n_vol = v_real * rng.normal(1, 0.0015, n)
        pcs_calc = pcs_crom * rng.normal(1, 0.0008, n)
        estado = np.array(["OK"] * n, dtype=object)
        modulado = (rng.random(n) < 0.30) if u.modula_habitual else (rng.random(n) < 0.003)
        ajuste = np.array([""] * n, dtype=object)
        if u.serie_habitual:
            ajuste[rng.integers(0, 10)::10] = "Prueba en Serie"
        incidencia = np.array([""] * n, dtype=object)

        # --- Incidencias reales
        n_epi = rng.poisson(4)
        for _ in range(n_epi):
            tipos = list(TIPOS_INCIDENCIA)
            tipo = rng.choice(tipos, p=[TIPOS_INCIDENCIA[t][0] for t in tipos])
            if tipo == "pcs_erroneo" and u.tipo_um != "Energia":
                tipo = "fallo_comunicacion"
            _, dmin, dmax, p_corr = TIPOS_INCIDENCIA[tipo]
            dur = int(rng.integers(dmin, dmax + 1))
            ini = int(rng.integers(30, n - dur - 1))
            idx = np.arange(ini, ini + dur)
            if (incidencia[idx] != "").any():
                continue
            if tipo == "fallo_comunicacion":
                n_vol[idx] = np.nan
                estado[idx] = "NC"
                modulado[idx] = True
            elif tipo == "deriva_conversor":
                deriva = rng.uniform(0.02, 0.06) * rng.choice([-1, 1])
                rampa = np.linspace(deriva / dur, deriva, dur)
                n_vol[idx] *= 1 + rampa
                idx = idx[np.abs(rampa) >= 0.005]  # al principio la deriva es imperceptible
                fin = min(ini + dur + int(rng.integers(0, 10)), n - 1)
                contrastes.append({"um_id": u.um_id, "fecha": fechas[fin], "linea": 1,
                                   "error_pct": round(deriva * 100 + rng.normal(0, 0.2), 2),
                                   "observaciones": "Deriva detectada en conversor, recalibrado"})
            elif tipo == "pico_lectura":
                n_vol[idx] *= rng.uniform(2, 5) if rng.random() < 0.5 else rng.uniform(0.1, 0.4)
                if rng.random() < 0.5:
                    estado[idx] = "ERROR"
            elif tipo == "pcs_erroneo":
                pcs_calc[idx] *= 1 + rng.uniform(0.015, 0.04) * rng.choice([-1, 1])
            elif tipo == "contador_bloqueado":
                n_vol[idx] = n_vol[ini - 1] if rng.random() < 0.5 else 0.0
            incidencia[idx] = tipo
            if rng.random() < p_corr:
                ajuste[idx] = AJUSTE_POR_TIPO[tipo]
            for i in idx:
                etiquetas.append({"um_id": u.um_id, "fecha": fechas[i], "tipo_incidencia": tipo})

        # --- SLM: dato calculado + lo que hicieron los usuarios
        s_vol = n_vol.copy()
        est = pd.Series(n_vol).rolling(7, min_periods=1).mean().shift(1).bfill().values
        s_vol[np.isnan(s_vol)] = est[np.isnan(s_vol)]  # modulación/estimación cuando no llega dato
        corregido = np.isin(ajuste, list(AJUSTE_POR_TIPO.values()))
        s_vol[corregido] = o_vol[corregido]  # el usuario regulariza con el mejor dato disponible
        modificado = corregido | (rng.random(n) < 0.002)  # + alguna modificación sin incidencia (ruido)
        ajuste[(modificado & ~corregido) & (ajuste == "")] = "Otros"

        neptuno.append(pd.DataFrame({
            "um_id": u.um_id, "fecha": fechas, "volumen_normalizado": n_vol.round(1),
            "pcs_calculado": pcs_calc.round(4), "energia": (n_vol * pcs_calc).round(0), "estado": estado}))
        slm.append(pd.DataFrame({
            "um_id": u.um_id, "fecha": fechas, "volumen_normalizado": s_vol.round(1),
            "energia": (s_vol * pcs_calc).round(0), "modulado": modulado.astype(int),
            "modificado": modificado.astype(int), "ajuste_tipo": ajuste}))
        orion.append(pd.DataFrame({"um_id": u.um_id, "fecha": fechas, "volumen_normalizado": o_vol.round(1),
                                   "energia": o_ene.round(0)}))
        # contrastaciones rutinarias cada ~90 días
        for d in range(int(rng.integers(0, 90)), n, 90):
            contrastes.append({"um_id": u.um_id, "fecha": fechas[d], "linea": 1,
                               "error_pct": round(rng.normal(0, 0.3), 2), "observaciones": ""})

    pd.concat(neptuno).to_csv(SALIDA / "neptuno.csv", index=False)
    pd.concat(slm).to_csv(SALIDA / "slm.csv", index=False)
    pd.concat(orion).to_csv(SALIDA / "orion.csv", index=False)
    cal.to_csv(SALIDA / "calidad_gas.csv", index=False)
    pd.DataFrame(contrastes).sort_values(["um_id", "fecha"]).to_csv(SALIDA / "contrastacion.csv", index=False)
    ums.drop(columns=["desfase_orion", "modula_habitual", "serie_habitual"]).to_csv(SALIDA / "um.csv", index=False)
    et = pd.DataFrame(etiquetas)
    et.to_csv(SALIDA / "etiquetas.csv", index=False)
    print(f"Generadas {len(ums)} UM × {n} días = {len(ums) * n:,} UM-día; "
          f"{len(et):,} UM-día con incidencia real ({len(et) / (len(ums) * n):.1%}) en {SALIDA}")


if __name__ == "__main__":
    main()
