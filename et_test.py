import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import time

# ---------------------------------------------------------
# 1. إعدادات الصفحة (System Configuration)
# ---------------------------------------------------------
# [Critical Fix]: التأكد من تفعيل وضع الشاشة العريضة
st.set_page_config(layout="wide", page_title="Riyadh VPP Command Center", page_icon="⚡", initial_sidebar_state="expanded")

# [Visual Styling]: التنسيق الأبيض الكامل (تابات، أزرار، سكرول)
st.markdown("""
<style>
    /* 1. الخلفية العامة */
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    
    /* 2. الأرقام */
    div[data-testid="stMetricValue"] { color: #39FF14 !important; font-family: 'Courier New', monospace; }
    
    /* 3. البطاقات */
    .kpi-card { background-color: #161B22; border: 1px solid #30363D; padding: 15px; border-radius: 5px; text-align: center; }

    /* 4. التابات (Tabs) - أبيض بخط أسود */
    .stTabs [data-baseweb="tab-list"] button {
        background-color: white !important;
        color: black !important;
        font-weight: bold !important;
        border-radius: 5px 5px 0px 0px;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        background-color: #f0f0f0 !important;
        border-bottom: 4px solid #39FF14 !important;
    }

    /* 5. إصلاح السكرول بار (Scrollbar) - إجباري */
    ::-webkit-scrollbar { width: 16px !important; height: 16px !important; }
    ::-webkit-scrollbar-track { background: #0E1117 !important; }
    ::-webkit-scrollbar-thumb { background-color: #FFFFFF !important; border-radius: 10px !important; border: 3px solid #0E1117 !important; }
    ::-webkit-scrollbar-thumb:hover { background-color: #cccccc !important; }

    /* 6. إصلاح الأزرار (Buttons) */
    div[data-testid="stButton"] > button {
        background-color: white !important;
        color: black !important;
        border: 1px solid #ccc !important;
        font-weight: bold !important;
    }
    div[data-testid="stButton"] > button:hover {
        background-color: #e0e0e0 !important;
        border-color: #39FF14 !important;
        color: black !important;
    }
    
    /* زر الإيقاف (الأحمر): يبقى أحمر */
    div[data-testid="stButton"] > button[kind="primary"] {
        background-color: #FF4B4B !important;
        color: white !important;
        border: none !important;
    }
    div[data-testid="stButton"] > button[kind="primary"]:hover {
        background-color: #ff3333 !important;
        color: white !important;
    }
    
    /* 7. [جديد] توسيع المحتوى (Padding Fix) */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        padding-left: 3rem;
        padding-right: 3rem;
    }

</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. الثوابت والمعايير الهندسية (Engineering Constants)
# ---------------------------------------------------------
AVG_CHARGER_CAPACITY_KW = 8.5 
CHARGING_CONCURRENCY_FACTOR = 0.85 
INVERTER_EFFICIENCY = 0.95 
GRID_VOLTAGE_LIMIT_MW = 250.0  # سقف الأمان للمحول الفرعي

# تعريف أوزان الأحياء (Data Model)
ZONE_WEIGHTS = {
    "Al-Olaya (Business)": {"load": 0.35, "ev_density": 0.40, "lat": 24.69, "lon": 46.68},
    "Al-Malqa (North)":    {"load": 0.25, "ev_density": 0.30, "lat": 24.81, "lon": 46.60},
    "Al-Nargis (Res.)":    {"load": 0.25, "ev_density": 0.20, "lat": 24.84, "lon": 46.66},
    "Diplomatic Quarter":  {"load": 0.15, "ev_density": 0.10, "lat": 24.68, "lon": 46.62},
}

# ---------------------------------------------------------
# 3. إدارة الحالة (Session State Management)
# ---------------------------------------------------------
if 'industrial_load' not in st.session_state: st.session_state.industrial_load = 4.0 
if 'global_grid_cap' not in st.session_state: st.session_state.global_grid_cap = 18.0 
if 'base_residential_load' not in st.session_state: st.session_state.base_residential_load = 14.3
if 'sell_price' not in st.session_state: st.session_state.sell_price = 0.80
if 'buy_price' not in st.session_state: st.session_state.buy_price = 0.18
if 'dispatch_active' not in st.session_state: st.session_state.dispatch_active = False

if 'zones_data' not in st.session_state:
    st.session_state.zones_data = {
        z: {"status": "STABLE", "payout": 0, "dispatched_mw": 0, "local_deficit": 0} 
        for z in ZONE_WEIGHTS.keys()
    }

# ---------------------------------------------------------
# 4. المحرك الفيزيائي (Physics Engine Core)
# ---------------------------------------------------------
def calculate_grid_physics(pct_charging, pct_v2g):
    total_fleet = 100000
    
    # 1. حمل الشحن
    num_charging = int(total_fleet * (pct_charging / 100))
    ev_load_total_kw = num_charging * AVG_CHARGER_CAPACITY_KW * CHARGING_CONCURRENCY_FACTOR 
    ev_load_gw = ev_load_total_kw / 1e6 
    
    # 2. الأحمال الكلية
    total_res_load = st.session_state.base_residential_load + ev_load_gw
    total_city_load = total_res_load + st.session_state.industrial_load
    
    # 3. العجز
    grid_cap = st.session_state.global_grid_cap
    raw_deficit = max(0, total_city_load - grid_cap)
    
    # 4. قدرة VPP
    num_v2g = int(total_fleet * (pct_v2g / 100))
    vpp_cap_mw = (num_v2g * AVG_CHARGER_CAPACITY_KW * INVERTER_EFFICIENCY) / 1000.0 
    
    return total_city_load, total_res_load, raw_deficit, vpp_cap_mw, num_charging, num_v2g

# ---------------------------------------------------------
# 5. دالة عرض الحي (Local View)
# ---------------------------------------------------------
def render_local_view(zone_name):
    pct_charging = st.session_state.get('pct_charging', 20)
    pct_v2g = st.session_state.get('pct_v2g', 60)
    _, total_res_load, raw_grid_deficit, _, _, _ = calculate_grid_physics(pct_charging, pct_v2g)
    
    params = ZONE_WEIGHTS[zone_name]
    total_fleet_riyadh = 100000
    
    local_load_gw = total_res_load * params["load"]
    local_cap_gw = st.session_state.global_grid_cap * 0.8 * params["load"] 
    local_deficit_gw = max(0, local_load_gw - local_cap_gw)
    st.session_state.zones_data[zone_name]['local_deficit'] = local_deficit_gw
    
    local_v2g_cars = int(total_fleet_riyadh * params["ev_density"] * (pct_v2g/100))
    available_vpp_mw = (local_v2g_cars * AVG_CHARGER_CAPACITY_KW * INVERTER_EFFICIENCY) / 1000.0
    
    st.title(f"📍 {zone_name} | Substation Control")
    
    current_total_dispatched = sum([d['dispatched_mw'] for z, d in st.session_state.zones_data.items()])
    net_deficit = max(0, raw_grid_deficit - (current_total_dispatched/1000))

    if net_deficit > 0.005:
         st.error(f"🚨 NATIONAL GRID ALERT: Remaining Deficit {net_deficit:.3f} GW. Support Needed!")
    elif raw_grid_deficit > 0:
         st.success(f"✅ GRID STABILIZED: VPP contribution active ({current_total_dispatched:.0f} MW).")
    else:
         st.info("ℹ️ Grid Status: Nominal.")

    st.markdown("---")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Local Load", f"{local_load_gw:.3f} GW")
    
    if local_deficit_gw > 0:
        c2.metric("Local Deficit", f"{local_deficit_gw:.3f} GW", "CRITICAL", delta_color="inverse")
    else:
        c2.metric("Local Deficit", "0.000 GW", "Stable")
        
    c3.metric("Available V2G", f"{available_vpp_mw:.1f} MW", f"{local_v2g_cars} Cars")
    
    is_dispatched = st.session_state.zones_data[zone_name]['dispatched_mw'] > 0
    status_text = "INJECTING" if is_dispatched else "STANDBY"
    status_color = "#39FF14" if is_dispatched else "#555"
    
    c4.markdown(f"""<div class="kpi-card" style="border-left: 5px solid {status_color};">
        <div style="font-size: 11px; color: #aaa;">STATUS</div>
        <div style="color: {status_color}; font-size: 20px; font-weight: bold;">{status_text}</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")
    
    target_dispatch = min(available_vpp_mw, GRID_VOLTAGE_LIMIT_MW)
    
    c_btn, c_rest = st.columns([1, 2])
    with c_btn:
        if not is_dispatched:
            if st.button(f"⚡ INJECT {target_dispatch:.0f} MW"):
                with st.spinner("Syncing Inverters..."):
                    time.sleep(0.5)
                    st.session_state.zones_data[zone_name]['dispatched_mw'] = target_dispatch
                    st.session_state.zones_data[zone_name]['payout'] = target_dispatch * 1000 * st.session_state.sell_price * 4
                    st.session_state.zones_data[zone_name]['status'] = "STABILIZED"
                    st.rerun()
        else:
            if st.button("🔴 STOP INJECTION"):
                st.session_state.zones_data[zone_name]['dispatched_mw'] = 0
                st.session_state.zones_data[zone_name]['payout'] = 0
                st.session_state.zones_data[zone_name]['status'] = "STABLE"
                st.rerun()
                
    lt1, lt2 = st.tabs(["🛡️ Infrastructure Health", "💰 Local Financials"])
    
    with lt1:
        st.subheader("Asset Health Monitoring")
        g1, g2 = st.columns(2)
        load_pct_weak = 95 if (not is_dispatched and local_deficit_gw > 0) else 40
        fig_w = go.Figure(go.Indicator(mode="gauge+number", value=load_pct_weak, title={'text': "Weak Transformers (Load %)"}, 
                                       gauge={'axis': {'range': [0, 120]}, 'bar': {'color': "red" if load_pct_weak > 90 else "#FFA500"}}))
        fig_w.update_layout(paper_bgcolor="#0E1117", font={'color': "white"}, height=250)
        g1.plotly_chart(fig_w, use_container_width=True)

        load_pct_strong = 60
        if is_dispatched: load_pct_strong = 75
        fig_s = go.Figure(go.Indicator(mode="gauge+number", value=load_pct_strong, title={'text': "Modern Substations (Load %)"}, 
                                       gauge={'axis': {'range': [0, 120]}, 'bar': {'color': "#00E676"}}))
        fig_s.update_layout(paper_bgcolor="#0E1117", font={'color': "white"}, height=250)
        g2.plotly_chart(fig_s, use_container_width=True)

    with lt2:
        if is_dispatched:
            f1, f2 = st.columns(2)
            f1.metric("Revenue (4h Cycle)", f"{st.session_state.zones_data[zone_name]['payout']:,.0f} SAR")
            f2.metric("Power Exported", f"{st.session_state.zones_data[zone_name]['dispatched_mw']:.1f} MW")
        else:
            st.info("No active settlement in this zone.")

# ---------------------------------------------------------
# 6. الواجهة الرئيسية والتحكم (Main Dashboard)
# ---------------------------------------------------------
with st.sidebar:
    st.title("🏙️ Scope Selection")
    options = ["Riyadh City Overview"] + list(ZONE_WEIGHTS.keys())
    selected_zone = st.selectbox("Select View", options)
    
    st.markdown("---")
    st.header("⚙️ Simulation Params")
    
    st.session_state.global_grid_cap = st.slider("Grid Capacity (GW)", 15.0, 25.0, 18.0)
    st.session_state.base_residential_load = st.slider("Base Res. Load (GW)", 8.0, 20.0, 14.3)
    st.session_state.industrial_load = st.slider("Ind. Load (GW)", 2.0, 8.0, 4.0)
    
    st.markdown("---")
    st.session_state.sell_price = st.slider("Sell Price (SAR/kWh)", 0.1, 2.0, 0.80)
    st.session_state.buy_price = st.slider("Buy Price (SAR/kWh)", 0.05, 1.0, 0.18)
    
    pct_charging = st.slider("Charging %", 0, 50, 20)
    pct_v2g = st.slider("V2G Ready %", 0, 80, 60)
    
    st.session_state.pct_charging = pct_charging
    st.session_state.pct_v2g = pct_v2g

    st.markdown("---")
    st.markdown("### 👨‍💻 Developed By")
    st.markdown("**Eng. Mohamed Alwedaa**")
    st.caption("Energy Data Strategist | V2G Specialist")
    
    linkedin_url = "https://www.linkedin.com/in/"
    st.markdown(f"""
    <a href="{linkedin_url}" target="_blank" style="text-decoration: none;">
        <button style="background-color: #0077b5; color: white; border: none; padding: 8px; border-radius: 5px; width: 100%; cursor: pointer;">
            Connect on LinkedIn
        </button>
    </a>
    """, unsafe_allow_html=True)

if selected_zone != "Riyadh City Overview":
    render_local_view(selected_zone)
else:
    st.title("🇸🇦 Riyadh City | VPP Strategic Analytics")
    
    total_city_load, total_res_load, raw_deficit, vpp_cap_mw, num_charging, num_v2g = calculate_grid_physics(pct_charging, pct_v2g)
    
    # ---------------------------------------------------------
    # [Dynamic Dispatch Loop] تحديث مستمر للحسابات
    # ---------------------------------------------------------
    if st.session_state.dispatch_active:
        deficit_mw = raw_deficit * 1000
        
        if vpp_cap_mw > 0:
            dispatch_ratio = min(1.0, deficit_mw / vpp_cap_mw) if deficit_mw > 0 else 0
        else:
            dispatch_ratio = 0
        
        for z, params in ZONE_WEIGHTS.items():
            local_fleet = 100000 * params['ev_density']
            local_max_cap = (local_fleet * (pct_v2g/100) * AVG_CHARGER_CAPACITY_KW * INVERTER_EFFICIENCY) / 1000
            
            target_local_dispatch = local_max_cap * dispatch_ratio
            
            st.session_state.zones_data[z]['dispatched_mw'] = target_local_dispatch
            st.session_state.zones_data[z]['payout'] = target_local_dispatch * 1000 * st.session_state.sell_price * 4
            st.session_state.zones_data[z]['status'] = "STABILIZED" if target_local_dispatch > 0 else "STABLE"

    manual_dispatch_sum = sum([d['dispatched_mw'] for z, d in st.session_state.zones_data.items()])
    total_dispatched_mw = manual_dispatch_sum

    net_deficit_gw = max(0, raw_deficit - (total_dispatched_mw/1000.0))

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Load", f"{total_city_load:.2f} GW")
    
    remaining_vpp_mw = max(0, vpp_cap_mw - total_dispatched_mw)
    one_car_capacity_mw = (AVG_CHARGER_CAPACITY_KW * INVERTER_EFFICIENCY) / 1000
    remaining_cars = int(remaining_vpp_mw / one_car_capacity_mw) if remaining_vpp_mw > 0 else 0

    k2.metric(
        "Unused VPP Cap", 
        f"{remaining_vpp_mw:.0f} MW", 
        f"{remaining_cars:,} Cars Left", 
        delta_color="off"
    )
    
    if raw_deficit > 0:
        if net_deficit_gw < 0.05 and total_dispatched_mw > 0:
            k3.metric("Grid Deficit", "STABILIZED ✅", f"Raw: {raw_deficit:.2f} GW")
        else:
            k3.metric("Grid Deficit", f"{net_deficit_gw:.3f} GW", "CRITICAL ⚠️", delta_color="inverse")
    else:
        k3.metric("Grid Deficit", "Surplus", "Stable")
        
    k4.metric("EV Load", f"+{num_charging*AVG_CHARGER_CAPACITY_KW/1000:.1f} MW", f"{num_charging:,} Cars")

    st.markdown("---")

    col_map_ctrl, col_act_ctrl = st.columns([3, 1])
    with col_act_ctrl:
        st.markdown("#### Central Dispatch")
        
        if st.session_state.dispatch_active:
            btn_txt = "🔴 SCRAM (STOP ALL)"
        else:
            btn_txt = "⚡ ACTIVATE ALL VPPs"

        if raw_deficit > 0:
            if st.button(btn_txt):
                st.session_state.dispatch_active = not st.session_state.dispatch_active
                if not st.session_state.dispatch_active:
                    for z in st.session_state.zones_data:
                        st.session_state.zones_data[z]['dispatched_mw'] = 0
                        st.session_state.zones_data[z]['payout'] = 0
                        st.session_state.zones_data[z]['status'] = "STABLE"
                st.rerun()
        else:
            st.info("Grid Stable. No Action Needed.")

    map_data = []
    for zone, params in ZONE_WEIGHTS.items():
        status = "STABLE"
        color = "#00E676"
        if net_deficit_gw > 0:
            status = "CRITICAL"
            color = "#FF4444"
        elif st.session_state.dispatch_active or st.session_state.zones_data[zone]['dispatched_mw'] > 0:
            status = "INJECTING"
            color = "#39FF14"
            
        map_data.append({
            "Zone": zone, "lat": params['lat'], "lon": params['lon'], 
            "Status": status, "Color": color, "Load": total_res_load * params['load']
        })
    
    df_map = pd.DataFrame(map_data)
    
    c_map1, c_map2 = st.columns([2, 1])
    with c_map1:
        st.subheader("🗺️ Live Grid Control Map")
        fig_map = px.scatter_mapbox(df_map, lat="lat", lon="lon", color="Status", size="Load",
                                    color_discrete_map={"INJECTING": "#39FF14", "CRITICAL": "#FF4444", "STABLE": "#00E676"},
                                    zoom=10, mapbox_style="carto-darkmatter", height=450, size_max=40)
        fig_map.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, paper_bgcolor="#0E1117", font=dict(color="white"))
        st.plotly_chart(fig_map, use_container_width=True)
    
    with c_map2:
        st.subheader("📊 Fleet Distribution")
        np.random.seed(99)
        fleet_map_df = pd.DataFrame({
            'lat': np.random.normal(24.71, 0.08, 1000),
            'lon': np.random.normal(46.67, 0.08, 1000),
            'Status': np.random.choice(['Charging', 'V2G Ready', 'Idle'], 1000, p=[pct_charging/100, pct_v2g/100, (100-pct_charging-pct_v2g)/100])
        })
        color_map_fleet = {'Charging': '#FF4444', 'V2G Ready': '#39FF14', 'Idle': '#DDDDDD'}
        fig_fleet = px.scatter_mapbox(fleet_map_df, lat="lat", lon="lon", color="Status", color_discrete_map=color_map_fleet, 
                                      zoom=9.5, mapbox_style="carto-darkmatter", height=450)
        
        # [Visual Update: White Labels + Legend]
        fig_fleet.update_layout(
            margin={"r":0,"t":0,"l":0,"b":0}, 
            paper_bgcolor="#0E1117", 
            font=dict(color="white"), 
            showlegend=True,
            legend=dict(x=0, y=1, bgcolor="rgba(0,0,0,0.5)", font=dict(size=10, color="white"))
        )
        st.plotly_chart(fig_fleet, use_container_width=True)

    t1, t2, t3 = st.tabs(["📈 Load Curve Analysis", "🔌 Charging Profile", "📋 Operations Settlement"])
    
    with t1:
        hours = list(range(24))
        base_curve = []
        for h in hours:
            if 0 <= h < 6:   factor = 0.55 
            elif 6 <= h < 11: factor = 0.75 
            elif 11 <= h < 15: factor = 0.65 
            elif 15 <= h < 19: factor = 0.98 
            elif 19 <= h < 23: factor = 0.85 
            else: factor = 0.60
            base_curve.append(total_city_load * (factor + np.random.normal(0, 0.01)))

        opt_curve = []
        dispatch_gw = total_dispatched_mw / 1000.0
        
        for h, val in enumerate(base_curve):
            if 15 <= h <= 18 and dispatch_gw > 0:
                opt_curve.append(max(0, val - dispatch_gw))
            else:
                opt_curve.append(val)

        fig_l = go.Figure()
        fig_l.add_vrect(x0=15, x1=18, fillcolor="red", opacity=0.1, annotation_text="Peak Zone", annotation_position="top left")
        fig_l.add_trace(go.Scatter(x=hours, y=base_curve, name='BAU Load', line=dict(color='#FF4444', width=2, dash='dot')))
        fig_l.add_trace(go.Scatter(x=hours, y=opt_curve, name='Optimized (V2G)', fill='tozeroy', line=dict(color='#39FF14', width=3)))
        
        # [Visual Update: White Labels]
        fig_l.update_layout(
            template="plotly_dark", height=350, 
            paper_bgcolor="#0E1117", margin=dict(l=0,r=0,t=10,b=0), 
            font=dict(color="white"), 
            xaxis_title="Hour", yaxis_title="GW",
            xaxis=dict(title_font=dict(color="white"), tickfont=dict(color="white")),
            yaxis=dict(title_font=dict(color="white"), tickfont=dict(color="white")),
            legend=dict(font=dict(color="white"))
        )
        st.plotly_chart(fig_l, use_container_width=True)

    with t2:
        hours = list(range(24))
        prices = [st.session_state.sell_price if 13 <= h <= 17 else st.session_state.buy_price for h in hours]
        charging_profile = [vpp_cap_mw * 0.1] * 24
        for h in range(7): charging_profile[h] = vpp_cap_mw * 0.8
        
        fig_sc = go.Figure()
        fig_sc.add_trace(go.Bar(x=hours, y=charging_profile, name='Fleet Load (MW)', marker_color='#00E676', yaxis='y'))
        fig_sc.add_trace(go.Scatter(x=hours, y=prices, name='Tariff (SAR)', line=dict(color='#FF5252', width=3, dash='dot'), yaxis='y2'))
        
        # [Visual Update: White Labels]
        fig_sc.update_layout(
            template="plotly_dark", paper_bgcolor="#0E1117", height=350, 
            font=dict(color="white"),
            yaxis=dict(title="MW", tickfont=dict(color="#00E676"), title_font=dict(color="#00E676")),
            yaxis2=dict(title="SAR", tickfont=dict(color="#FF5252"), title_font=dict(color="#FF5252"), overlaying="y", side="right"),
            legend=dict(x=0, y=1.1, orientation="h", font=dict(color="white"))
        )
        st.plotly_chart(fig_sc, use_container_width=True)

    with t3:
        st.subheader("📊 Zone Operations & Settlement Report")
        
        table_data = []
        total_active_cars = 0
        total_payout = 0
        total_mw_table = 0
        
        for zone, params in ZONE_WEIGHTS.items():
            state_data = st.session_state.zones_data[zone]
            z_mw = state_data['dispatched_mw']
            z_payout = state_data['payout']
            
            if z_mw > 0:
                if st.session_state.dispatch_active:
                    status = "🟢 Active (Central)"
                else:
                    status = "🟢 Active (Local)"
                
                one_car_capacity_mw = (AVG_CHARGER_CAPACITY_KW * INVERTER_EFFICIENCY) / 1000
                z_cars = int(z_mw / one_car_capacity_mw)
            else:
                status = "⚪ Standby"
                z_cars = 0

            table_data.append({
                "Zone (District)": zone,
                "Status": status,
                "Active V2G Cars": f"{z_cars:,}",
                "Dispatched Power (MW)": f"{z_mw:.2f}",
                "Est. Payout (SAR)": f"{z_payout:,.0f}"
            })
            
            total_active_cars += z_cars
            total_mw_table += z_mw
            total_payout += z_payout

        df_ops = pd.DataFrame(table_data)
        st.dataframe(
            df_ops, 
            use_container_width=True, 
            column_config={
                "Status": st.column_config.TextColumn("System Status"),
                "Est. Payout (SAR)": st.column_config.TextColumn("Payment Due (SAR)"),
            }
        )
        
        st.markdown("---")
        c_tot1, c_tot2, c_tot3 = st.columns(3)
        c_tot1.metric("Total Participating Cars", f"{total_active_cars:,}")
        c_tot2.metric("Total Power Dispatched", f"{total_mw_table:.2f} MW")
        c_tot3.metric("Total Settlement Amount", f"{total_payout:,.0f} SAR", "4 Hours Cycle")
