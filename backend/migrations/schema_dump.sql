-- NexaFreight Production Schema Dump (v1.0.0 Sealed Baseline)
-- Generated from SQLAlchemy declarative metadata (PostgreSQL/SQLite DDL)

CREATE TABLE corridor_alternatives (
	id INTEGER NOT NULL, 
	option_key VARCHAR(50) NOT NULL, 
	display_name VARCHAR(255) NOT NULL, 
	applicable_disruption_types_json TEXT NOT NULL, 
	route_template_json TEXT NOT NULL, 
	cost_delta_factor FLOAT NOT NULL, 
	time_delta_hours FLOAT NOT NULL, 
	co2_delta_factor FLOAT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_corridor_alternatives PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_corridor_alternatives_option_key ON corridor_alternatives (option_key);

CREATE TABLE external_events (
	id INTEGER NOT NULL, 
	source VARCHAR(40) NOT NULL, 
	external_id VARCHAR(120) NOT NULL, 
	event_type VARCHAR(40) NOT NULL, 
	title TEXT NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	latitude FLOAT, 
	longitude FLOAT, 
	event_time DATETIME, 
	fetched_at DATETIME DEFAULT now() NOT NULL, 
	raw_json TEXT, 
	provenance VARCHAR(20) DEFAULT 'REAL' NOT NULL, 
	CONSTRAINT pk_external_events PRIMARY KEY (id), 
	CONSTRAINT uq_external_events_source_external_id UNIQUE (source, external_id)
);

CREATE INDEX ix_external_events_event_time ON external_events (event_time);

CREATE TABLE locations (
	id INTEGER NOT NULL, 
	locode VARCHAR(10) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	country_code VARCHAR(2) NOT NULL, 
	location_type VARCHAR(20) NOT NULL, 
	latitude FLOAT NOT NULL, 
	longitude FLOAT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_locations PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_locations_locode ON locations (locode);

CREATE TABLE network_nodes (
	id INTEGER NOT NULL, 
	locode VARCHAR(10) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	node_type VARCHAR(30) NOT NULL, 
	modes_json TEXT NOT NULL, 
	latitude FLOAT NOT NULL, 
	longitude FLOAT NOT NULL, 
	country_code VARCHAR(2) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_network_nodes PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_network_nodes_locode ON network_nodes (locode);

CREATE TABLE parameter_empirical (
	key VARCHAR(100) NOT NULL, 
	value VARCHAR(255) NOT NULL, 
	unit VARCHAR(50), 
	source VARCHAR(255) NOT NULL, 
	as_of DATETIME NOT NULL, 
	derivation_method TEXT NOT NULL, 
	sample_count INTEGER, 
	valid_from DATETIME, 
	valid_to DATETIME, 
	CONSTRAINT pk_parameter_empirical PRIMARY KEY (key)
);

CREATE TABLE parameter_policy (
	key VARCHAR(100) NOT NULL, 
	value VARCHAR(255) NOT NULL, 
	unit VARCHAR(50), 
	owner VARCHAR(100) NOT NULL, 
	rationale TEXT NOT NULL, 
	updated_at DATETIME DEFAULT now() NOT NULL, 
	CONSTRAINT pk_parameter_policy PRIMARY KEY (key)
);

CREATE TABLE parties (
	id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	city VARCHAR(80), 
	country_code VARCHAR(2) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_parties PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_parties_name ON parties (name);

CREATE TABLE users (
	id INTEGER NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	hashed_password VARCHAR(255) NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_users PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE vessels (
	id INTEGER NOT NULL, 
	mmsi INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	call_sign VARCHAR(20), 
	typical_lanes_json TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_vessels PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_vessels_mmsi ON vessels (mmsi);

CREATE TABLE audit_logs (
	id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	actor_type VARCHAR(20) NOT NULL, 
	actor_id INTEGER, 
	actor_name VARCHAR(255) NOT NULL, 
	action VARCHAR(100) NOT NULL, 
	entity_type VARCHAR(50), 
	entity_id VARCHAR(100), 
	input_hash VARCHAR(64), 
	output_hash VARCHAR(64), 
	details_json TEXT, 
	CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
	CONSTRAINT fk_audit_logs_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

CREATE TABLE network_edges (
	id INTEGER NOT NULL, 
	from_node_id INTEGER NOT NULL, 
	to_node_id INTEGER NOT NULL, 
	mode VARCHAR(20) NOT NULL, 
	distance_km FLOAT NOT NULL, 
	transit_speed_param_key VARCHAR(100) NOT NULL, 
	base_cost_param_key VARCHAR(100) NOT NULL, 
	co2_intensity_param_key VARCHAR(100) NOT NULL, 
	geometry_json TEXT, 
	capacity_teu INTEGER, 
	reliability FLOAT NOT NULL, 
	is_dfc BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_network_edges PRIMARY KEY (id), 
	CONSTRAINT fk_network_edges_from_node_id_network_nodes FOREIGN KEY(from_node_id) REFERENCES network_nodes (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_network_edges_to_node_id_network_nodes FOREIGN KEY(to_node_id) REFERENCES network_nodes (id) ON DELETE RESTRICT
);

CREATE INDEX ix_network_edges_from_node_id ON network_edges (from_node_id);

CREATE INDEX ix_network_edges_to_node_id ON network_edges (to_node_id);

CREATE TABLE ports (
	id INTEGER NOT NULL, 
	location_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_ports PRIMARY KEY (id), 
	CONSTRAINT uq_ports_location_id UNIQUE (location_id), 
	CONSTRAINT fk_ports_location_id_locations FOREIGN KEY(location_id) REFERENCES locations (id) ON DELETE RESTRICT
);

CREATE TABLE shipments (
	origin_id INTEGER NOT NULL, 
	destination_id INTEGER NOT NULL, 
	primary_transport_mode VARCHAR(20) NOT NULL, 
	cargo_class VARCHAR(20) NOT NULL, 
	container_count INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	route_version INTEGER NOT NULL, 
	planned_departure DATETIME, 
	strictest_sla_deadline DATETIME, 
	parent_shipment_id VARCHAR(36), 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	provenance VARCHAR(20) NOT NULL, 
	CONSTRAINT pk_shipments PRIMARY KEY (id), 
	CONSTRAINT fk_shipments_origin_id_locations FOREIGN KEY(origin_id) REFERENCES locations (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_shipments_destination_id_locations FOREIGN KEY(destination_id) REFERENCES locations (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_shipments_parent_shipment_id_shipments FOREIGN KEY(parent_shipment_id) REFERENCES shipments (id) ON DELETE SET NULL
);

CREATE INDEX ix_shipments_status ON shipments (status);

CREATE INDEX ix_shipments_planned_departure ON shipments (planned_departure);

CREATE TABLE transshipment_links (
	id INTEGER NOT NULL, 
	node_id INTEGER NOT NULL, 
	min_dwell_h FLOAT NOT NULL, 
	max_dwell_h FLOAT NOT NULL, 
	handling_cost_usd FLOAT NOT NULL, 
	dg_capable BOOLEAN NOT NULL, 
	reefer_capable BOOLEAN NOT NULL, 
	CONSTRAINT pk_transshipment_links PRIMARY KEY (id), 
	CONSTRAINT fk_transshipment_links_node_id_network_nodes FOREIGN KEY(node_id) REFERENCES network_nodes (id) ON DELETE CASCADE
);

CREATE INDEX ix_transshipment_links_node_id ON transshipment_links (node_id);

CREATE TABLE edge_schedules (
	id INTEGER NOT NULL, 
	edge_id INTEGER NOT NULL, 
	service_name VARCHAR(100) NOT NULL, 
	departure_at DATETIME NOT NULL, 
	arrival_at DATETIME NOT NULL, 
	cutoff_at DATETIME, 
	capacity_remaining INTEGER, 
	provenance VARCHAR(20) NOT NULL, 
	CONSTRAINT pk_edge_schedules PRIMARY KEY (id), 
	CONSTRAINT fk_edge_schedules_edge_id_network_edges FOREIGN KEY(edge_id) REFERENCES network_edges (id) ON DELETE CASCADE
);

CREATE INDEX ix_edge_schedules_edge_id ON edge_schedules (edge_id);

CREATE INDEX ix_edge_schedules_departure_at ON edge_schedules (departure_at);

CREATE TABLE legs (
	id INTEGER NOT NULL, 
	shipment_id VARCHAR(36) NOT NULL, 
	sequence_number INTEGER NOT NULL, 
	route_version INTEGER NOT NULL, 
	transport_mode VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	origin_id INTEGER NOT NULL, 
	destination_id INTEGER NOT NULL, 
	vessel_id INTEGER, 
	flight_number VARCHAR(20), 
	planned_departure DATETIME NOT NULL, 
	planned_arrival DATETIME NOT NULL, 
	actual_departure DATETIME, 
	actual_arrival DATETIME, 
	route_geometry_json TEXT, 
	distance_km FLOAT, 
	co2_kg FLOAT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	provenance VARCHAR(20) NOT NULL, 
	CONSTRAINT pk_legs PRIMARY KEY (id), 
	CONSTRAINT fk_legs_shipment_id_shipments FOREIGN KEY(shipment_id) REFERENCES shipments (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_legs_origin_id_locations FOREIGN KEY(origin_id) REFERENCES locations (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_legs_destination_id_locations FOREIGN KEY(destination_id) REFERENCES locations (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_legs_vessel_id_vessels FOREIGN KEY(vessel_id) REFERENCES vessels (id) ON DELETE SET NULL
);

CREATE INDEX ix_legs_shipment_id ON legs (shipment_id);

CREATE TABLE orders (
	id INTEGER NOT NULL, 
	order_number VARCHAR(50) NOT NULL, 
	shipment_id VARCHAR(36), 
	order_date DATETIME, 
	sla_deadline DATETIME NOT NULL, 
	revenue FLOAT NOT NULL, 
	shipping_cost FLOAT NOT NULL, 
	sla_status VARCHAR(20) NOT NULL, 
	shipper_id INTEGER, 
	consignee_id INTEGER, 
	carrier_id INTEGER, 
	shipping_mode VARCHAR(20) NOT NULL, 
	cargo_class VARCHAR(20) NOT NULL, 
	weight_kg FLOAT, 
	volume_m3 FLOAT, 
	historical_late_delivery BOOLEAN, 
	real_shipping_days FLOAT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_orders PRIMARY KEY (id), 
	CONSTRAINT fk_orders_shipment_id_shipments FOREIGN KEY(shipment_id) REFERENCES shipments (id) ON DELETE SET NULL, 
	CONSTRAINT fk_orders_shipper_id_parties FOREIGN KEY(shipper_id) REFERENCES parties (id) ON DELETE SET NULL, 
	CONSTRAINT fk_orders_consignee_id_parties FOREIGN KEY(consignee_id) REFERENCES parties (id) ON DELETE SET NULL, 
	CONSTRAINT fk_orders_carrier_id_parties FOREIGN KEY(carrier_id) REFERENCES parties (id) ON DELETE SET NULL
);

CREATE INDEX ix_orders_order_date ON orders (order_date);

CREATE INDEX ix_orders_shipment_id ON orders (shipment_id);

CREATE UNIQUE INDEX ix_orders_order_number ON orders (order_number);

CREATE TABLE port_daily_stats (
	id INTEGER NOT NULL, 
	port_id INTEGER NOT NULL, 
	stat_date DATE NOT NULL, 
	congestion_index FLOAT NOT NULL, 
	source VARCHAR(40) DEFAULT 'SIMULATED' NOT NULL, 
	CONSTRAINT pk_port_daily_stats PRIMARY KEY (id), 
	CONSTRAINT uq_port_daily_stats_port_id_stat_date UNIQUE (port_id, stat_date), 
	CONSTRAINT fk_port_daily_stats_port_id_ports FOREIGN KEY(port_id) REFERENCES ports (id) ON DELETE CASCADE
);

CREATE INDEX ix_port_daily_stats_stat_date ON port_daily_stats (stat_date);

CREATE TABLE route_plans (
	id INTEGER NOT NULL, 
	shipment_id VARCHAR(36) NOT NULL, 
	plan_type VARCHAR(20) NOT NULL, 
	priority VARCHAR(20) NOT NULL, 
	rank INTEGER NOT NULL, 
	recommended BOOLEAN NOT NULL, 
	total_cost_usd FLOAT NOT NULL, 
	total_time_h FLOAT NOT NULL, 
	total_co2_kg FLOAT NOT NULL, 
	reliability_score FLOAT NOT NULL, 
	risk_index FLOAT NOT NULL, 
	score FLOAT NOT NULL, 
	rationale TEXT, 
	objective_weights_json TEXT NOT NULL, 
	provenance VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_route_plans PRIMARY KEY (id), 
	CONSTRAINT fk_route_plans_shipment_id_shipments FOREIGN KEY(shipment_id) REFERENCES shipments (id) ON DELETE CASCADE
);

CREATE INDEX ix_route_plans_shipment_id ON route_plans (shipment_id);

CREATE TABLE disruptions (
	shipment_id VARCHAR(36) NOT NULL, 
	leg_id INTEGER, 
	disruption_type VARCHAR(50) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	description TEXT NOT NULL, 
	detected_at DATETIME NOT NULL, 
	resolved_at DATETIME, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_disruptions PRIMARY KEY (id), 
	CONSTRAINT uq_disruptions_active_per_shipment_leg_type UNIQUE (shipment_id, leg_id, disruption_type, status), 
	CONSTRAINT fk_disruptions_shipment_id_shipments FOREIGN KEY(shipment_id) REFERENCES shipments (id) ON DELETE CASCADE, 
	CONSTRAINT fk_disruptions_leg_id_legs FOREIGN KEY(leg_id) REFERENCES legs (id) ON DELETE SET NULL
);

CREATE INDEX ix_disruptions_shipment_id ON disruptions (shipment_id);

CREATE TABLE order_items (
	id INTEGER NOT NULL, 
	order_id INTEGER NOT NULL, 
	product_category VARCHAR(100) NOT NULL, 
	quantity INTEGER NOT NULL, 
	unit_price FLOAT NOT NULL, 
	CONSTRAINT pk_order_items PRIMARY KEY (id), 
	CONSTRAINT fk_order_items_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE CASCADE
);

CREATE TABLE position_reports (
	id INTEGER NOT NULL, 
	leg_id INTEGER NOT NULL, 
	asset_type VARCHAR(20) NOT NULL, 
	mmsi INTEGER, 
	latitude FLOAT NOT NULL, 
	longitude FLOAT NOT NULL, 
	heading FLOAT, 
	speed_knots FLOAT, 
	reported_at DATETIME NOT NULL, 
	provenance VARCHAR(20) NOT NULL, 
	CONSTRAINT pk_position_reports PRIMARY KEY (id), 
	CONSTRAINT uq_position_reports_leg_reported_at UNIQUE (leg_id, reported_at), 
	CONSTRAINT fk_position_reports_leg_id_legs FOREIGN KEY(leg_id) REFERENCES legs (id) ON DELETE CASCADE
);

CREATE INDEX ix_position_reports_leg_id ON position_reports (leg_id);

CREATE INDEX ix_position_reports_reported_at ON position_reports (reported_at);

CREATE TABLE route_legs (
	id INTEGER NOT NULL, 
	plan_id INTEGER NOT NULL, 
	sequence_number INTEGER NOT NULL, 
	mode VARCHAR(20) NOT NULL, 
	from_node_id INTEGER NOT NULL, 
	to_node_id INTEGER NOT NULL, 
	edge_id INTEGER, 
	schedule_id INTEGER, 
	departure_at DATETIME NOT NULL, 
	arrival_at DATETIME NOT NULL, 
	cost_usd FLOAT NOT NULL, 
	transit_h FLOAT NOT NULL, 
	co2_kg FLOAT NOT NULL, 
	reliability FLOAT NOT NULL, 
	provenance VARCHAR(20) NOT NULL, 
	CONSTRAINT pk_route_legs PRIMARY KEY (id), 
	CONSTRAINT fk_route_legs_plan_id_route_plans FOREIGN KEY(plan_id) REFERENCES route_plans (id) ON DELETE CASCADE, 
	CONSTRAINT fk_route_legs_from_node_id_network_nodes FOREIGN KEY(from_node_id) REFERENCES network_nodes (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_route_legs_to_node_id_network_nodes FOREIGN KEY(to_node_id) REFERENCES network_nodes (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_route_legs_edge_id_network_edges FOREIGN KEY(edge_id) REFERENCES network_edges (id) ON DELETE SET NULL, 
	CONSTRAINT fk_route_legs_schedule_id_edge_schedules FOREIGN KEY(schedule_id) REFERENCES edge_schedules (id) ON DELETE SET NULL
);

CREATE INDEX ix_route_legs_plan_id ON route_legs (plan_id);

CREATE TABLE alerts (
	disruption_id VARCHAR(36) NOT NULL, 
	shipment_id VARCHAR(36) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	financial_exposure FLOAT NOT NULL, 
	sla_breach_details_json TEXT, 
	acknowledged_by INTEGER, 
	acknowledged_at DATETIME, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_alerts PRIMARY KEY (id), 
	CONSTRAINT uq_alerts_disruption_id UNIQUE (disruption_id), 
	CONSTRAINT uq_alerts_disruption_id UNIQUE (disruption_id), 
	CONSTRAINT fk_alerts_disruption_id_disruptions FOREIGN KEY(disruption_id) REFERENCES disruptions (id) ON DELETE CASCADE, 
	CONSTRAINT fk_alerts_shipment_id_shipments FOREIGN KEY(shipment_id) REFERENCES shipments (id) ON DELETE CASCADE, 
	CONSTRAINT fk_alerts_acknowledged_by_users FOREIGN KEY(acknowledged_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_alerts_shipment_id ON alerts (shipment_id);

CREATE INDEX ix_alerts_severity ON alerts (severity);

CREATE TABLE decisions (
	alert_id VARCHAR(36) NOT NULL, 
	shipment_id VARCHAR(36) NOT NULL, 
	action VARCHAR(20) NOT NULL, 
	chosen_option_key VARCHAR(50), 
	options_snapshot_json TEXT NOT NULL, 
	financial_impact FLOAT NOT NULL, 
	route_version_before INTEGER NOT NULL, 
	route_version_after INTEGER NOT NULL, 
	approved_by INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_decisions PRIMARY KEY (id), 
	CONSTRAINT uq_decisions_alert_id UNIQUE (alert_id), 
	CONSTRAINT uq_decisions_alert_id UNIQUE (alert_id), 
	CONSTRAINT fk_decisions_alert_id_alerts FOREIGN KEY(alert_id) REFERENCES alerts (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_decisions_shipment_id_shipments FOREIGN KEY(shipment_id) REFERENCES shipments (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_decisions_approved_by_users FOREIGN KEY(approved_by) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE INDEX ix_decisions_shipment_id ON decisions (shipment_id);

CREATE TABLE decision_outcomes (
	decision_id VARCHAR(36) NOT NULL, 
	shipment_id VARCHAR(36) NOT NULL, 
	chosen_option_key VARCHAR(50) NOT NULL, 
	recommended_option_key VARCHAR(50), 
	override_reason TEXT, 
	predicted_total_impact_usd FLOAT NOT NULL, 
	predicted_cost_delta_usd FLOAT, 
	predicted_sla_usd FLOAT, 
	predicted_demurrage_usd FLOAT, 
	predicted_carbon_usd FLOAT, 
	predicted_revised_eta DATETIME, 
	baseline_planned_arrival DATETIME, 
	realized_arrival_delta_h FLOAT, 
	realized_penalty_usd FLOAT, 
	realized_route_version INTEGER, 
	outcome_finalized_at DATETIME, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	CONSTRAINT pk_decision_outcomes PRIMARY KEY (id), 
	CONSTRAINT uq_decision_outcomes_decision_id UNIQUE (decision_id), 
	CONSTRAINT fk_decision_outcomes_decision_id_decisions FOREIGN KEY(decision_id) REFERENCES decisions (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_decision_outcomes_shipment_id_shipments FOREIGN KEY(shipment_id) REFERENCES shipments (id) ON DELETE RESTRICT
);

CREATE INDEX ix_decision_outcomes_shipment_id ON decision_outcomes (shipment_id);
