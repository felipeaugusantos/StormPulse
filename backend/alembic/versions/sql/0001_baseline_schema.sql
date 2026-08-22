--
-- Name: alert_event_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.alert_event_type AS ENUM (
    'STORM_DETECTED',
    'STORM_APPROACHING',
    'STORM_INTENSIFIED',
    'STORM_ENTERED_MONITORING_AREA',
    'STORM_RISK_CHANGED',
    'STORM_PASSED',
    'SATELLITE_WATCH_DETECTED',
    'SATELLITE_WATCH_DISSIPATED',
    'FROST_WARNING',
    'DRY_SPELL_WARNING'
);


--
-- Name: alert_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.alert_type AS ENUM (
    'RAIN_INTENSE',
    'SEVERE_STORM',
    'STRONG_WIND',
    'HAIL',
    'LIGHTNING',
    'SEVERE_CELL'
);


--
-- Name: notification_channel; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.notification_channel AS ENUM (
    'PUSH',
    'EMAIL'
);


--
-- Name: notification_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.notification_status AS ENUM (
    'PENDING',
    'SENT',
    'FAILED',
    'SUPPRESSED'
);


--
-- Name: report_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.report_status AS ENUM (
    'PENDING',
    'CONFIRMED',
    'REJECTED'
);


--
-- Name: report_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.report_type AS ENUM (
    'HAIL',
    'STRONG_WIND',
    'FLOODING',
    'RAIN_INTENSE',
    'FALLEN_TREE',
    'LIGHTNING'
);


--
-- Name: risk_level; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.risk_level AS ENUM (
    'GREEN',
    'YELLOW',
    'ORANGE',
    'RED'
);


--
-- Name: storm_severity; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.storm_severity AS ENUM (
    'WEAK',
    'MODERATE',
    'STRONG',
    'SEVERE'
);


--
-- Name: track_trend; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.track_trend AS ENUM (
    'INTENSIFYING',
    'STEADY',
    'WEAKENING'
);


--
-- Name: user_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.user_role AS ENUM (
    'ADMIN',
    'USER',
    'METEOROLOGIST',
    'COMPANY_ADMIN',
    'OPERATOR'
);


--
-- Name: weather_source_kind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.weather_source_kind AS ENUM (
    'MOCK',
    'RADAR',
    'SATELLITE',
    'STATION',
    'OFFICIAL_WARNING',
    'FORECAST_MODEL'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alert_preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alert_preferences (
    location_id uuid NOT NULL,
    alert_type public.alert_type NOT NULL,
    enabled boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alerts (
    user_id uuid NOT NULL,
    location_id uuid NOT NULL,
    storm_cell_id uuid,
    storm_risk_id uuid,
    convective_watch_id uuid,
    event_type public.alert_event_type NOT NULL,
    level public.risk_level NOT NULL,
    title character varying(160) NOT NULL,
    message text NOT NULL,
    dedup_key character varying(200) NOT NULL,
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: convective_watches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.convective_watches (
    first_detected_at timestamp with time zone NOT NULL,
    detected_at timestamp with time zone NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    centroid public.geography(Point,4326),
    geometry public.geography(Polygon,4326),
    min_brightness_temp_k double precision NOT NULL,
    area_km2 double precision,
    speed_kmh double precision,
    direction_deg double precision,
    is_active boolean NOT NULL,
    is_mock boolean NOT NULL,
    experimental boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: lightning_strikes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lightning_strikes (
    detected_at timestamp with time zone NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    is_mock boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: locations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locations (
    user_id uuid NOT NULL,
    name character varying(120) NOT NULL,
    kind character varying(40) NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    radius_km double precision NOT NULL,
    parent_location_id uuid,
    crop character varying(60),
    boundary_geojson text,
    color character varying(7),
    geom public.geography(Point,4326),
    is_active boolean NOT NULL,
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    alert_id uuid NOT NULL,
    user_id uuid NOT NULL,
    channel public.notification_channel NOT NULL,
    status public.notification_status NOT NULL,
    sent_at timestamp with time zone,
    error text,
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: push_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.push_subscriptions (
    user_id uuid NOT NULL,
    platform character varying(20) NOT NULL,
    endpoint text,
    p256dh text,
    auth text,
    expo_push_token text,
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: radar_frames; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.radar_frames (
    weather_source_id uuid NOT NULL,
    captured_at timestamp with time zone NOT NULL,
    is_mock boolean NOT NULL,
    meta jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: satellite_images; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.satellite_images (
    captured_at timestamp with time zone NOT NULL,
    bbox_lon_min double precision NOT NULL,
    bbox_lat_min double precision NOT NULL,
    bbox_lon_max double precision NOT NULL,
    bbox_lat_max double precision NOT NULL,
    band character varying(16) NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    png_data bytea NOT NULL,
    is_mock boolean NOT NULL,
    experimental boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: storm_cells; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storm_cells (
    weather_source_id uuid,
    detected_at timestamp with time zone NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    geometry public.geography(Polygon,4326),
    centroid public.geography(Point,4326),
    max_reflectivity double precision,
    average_reflectivity double precision,
    area_km2 double precision,
    severity public.storm_severity NOT NULL,
    is_mock boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: storm_observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storm_observations (
    storm_track_id uuid NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    geom public.geography(Point,4326),
    speed_kmh double precision,
    direction_deg double precision,
    intensity double precision,
    trend public.track_trend,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: storm_risks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storm_risks (
    location_id uuid NOT NULL,
    storm_cell_id uuid,
    severity public.risk_level NOT NULL,
    rain_risk double precision NOT NULL,
    wind_risk double precision NOT NULL,
    hail_risk double precision NOT NULL,
    lightning_risk double precision NOT NULL,
    storm_distance_km double precision,
    storm_speed_kmh double precision,
    eta_minutes integer,
    computed_at timestamp with time zone NOT NULL,
    is_mock boolean NOT NULL,
    experimental boolean NOT NULL,
    detail jsonb NOT NULL,
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: storm_tracks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storm_tracks (
    storm_cell_id uuid NOT NULL,
    started_at timestamp with time zone NOT NULL,
    last_observed_at timestamp with time zone NOT NULL,
    is_active boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tenants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenants (
    name character varying(120) NOT NULL,
    slug character varying(80) NOT NULL,
    is_active boolean NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_reports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_reports (
    user_id uuid NOT NULL,
    type public.report_type NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    geom public.geography(Point,4326),
    description text,
    photo_url character varying(500),
    confidence double precision NOT NULL,
    status public.report_status NOT NULL,
    reported_at timestamp with time zone NOT NULL,
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    email character varying(255) NOT NULL,
    full_name character varying(120),
    hashed_password character varying(255) NOT NULL,
    google_sub character varying(255),
    role public.user_role NOT NULL,
    is_active boolean NOT NULL,
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: weather_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.weather_sources (
    name character varying(120) NOT NULL,
    kind public.weather_source_kind NOT NULL,
    is_active boolean NOT NULL,
    config jsonb NOT NULL,
    id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alert_preferences alert_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alert_preferences
    ADD CONSTRAINT alert_preferences_pkey PRIMARY KEY (id);


--
-- Name: alerts alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);


--
-- Name: convective_watches convective_watches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.convective_watches
    ADD CONSTRAINT convective_watches_pkey PRIMARY KEY (id);


--
-- Name: lightning_strikes lightning_strikes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lightning_strikes
    ADD CONSTRAINT lightning_strikes_pkey PRIMARY KEY (id);


--
-- Name: locations locations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: push_subscriptions push_subscriptions_endpoint_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_endpoint_key UNIQUE (endpoint);


--
-- Name: push_subscriptions push_subscriptions_expo_push_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_expo_push_token_key UNIQUE (expo_push_token);


--
-- Name: push_subscriptions push_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: radar_frames radar_frames_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.radar_frames
    ADD CONSTRAINT radar_frames_pkey PRIMARY KEY (id);


--
-- Name: satellite_images satellite_images_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.satellite_images
    ADD CONSTRAINT satellite_images_pkey PRIMARY KEY (id);


--
-- Name: storm_cells storm_cells_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storm_cells
    ADD CONSTRAINT storm_cells_pkey PRIMARY KEY (id);


--
-- Name: storm_observations storm_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storm_observations
    ADD CONSTRAINT storm_observations_pkey PRIMARY KEY (id);


--
-- Name: storm_risks storm_risks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storm_risks
    ADD CONSTRAINT storm_risks_pkey PRIMARY KEY (id);


--
-- Name: storm_tracks storm_tracks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storm_tracks
    ADD CONSTRAINT storm_tracks_pkey PRIMARY KEY (id);


--
-- Name: tenants tenants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);


--
-- Name: alert_preferences uq_alert_pref_location_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alert_preferences
    ADD CONSTRAINT uq_alert_pref_location_type UNIQUE (location_id, alert_type);


--
-- Name: alerts uq_alert_tenant_dedup; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT uq_alert_tenant_dedup UNIQUE (tenant_id, dedup_key);


--
-- Name: user_reports user_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_reports
    ADD CONSTRAINT user_reports_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: weather_sources weather_sources_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.weather_sources
    ADD CONSTRAINT weather_sources_name_key UNIQUE (name);


--
-- Name: weather_sources weather_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.weather_sources
    ADD CONSTRAINT weather_sources_pkey PRIMARY KEY (id);


--
-- Name: idx_convective_watches_centroid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_convective_watches_centroid ON public.convective_watches USING gist (centroid);


--
-- Name: idx_convective_watches_geometry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_convective_watches_geometry ON public.convective_watches USING gist (geometry);


--
-- Name: idx_locations_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_locations_geom ON public.locations USING gist (geom);


--
-- Name: idx_storm_cells_centroid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_storm_cells_centroid ON public.storm_cells USING gist (centroid);


--
-- Name: idx_storm_cells_geometry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_storm_cells_geometry ON public.storm_cells USING gist (geometry);


--
-- Name: idx_storm_observations_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_storm_observations_geom ON public.storm_observations USING gist (geom);


--
-- Name: idx_user_reports_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_reports_geom ON public.user_reports USING gist (geom);


--
-- Name: ix_alert_preferences_location_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alert_preferences_location_id ON public.alert_preferences USING btree (location_id);


--
-- Name: ix_alerts_convective_watch_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alerts_convective_watch_id ON public.alerts USING btree (convective_watch_id);


--
-- Name: ix_alerts_location_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alerts_location_id ON public.alerts USING btree (location_id);


--
-- Name: ix_alerts_storm_cell_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alerts_storm_cell_id ON public.alerts USING btree (storm_cell_id);


--
-- Name: ix_alerts_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alerts_tenant_id ON public.alerts USING btree (tenant_id);


--
-- Name: ix_alerts_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alerts_user_id ON public.alerts USING btree (user_id);


--
-- Name: ix_convective_watches_detected_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_convective_watches_detected_at ON public.convective_watches USING btree (detected_at);


--
-- Name: ix_convective_watches_is_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_convective_watches_is_active ON public.convective_watches USING btree (is_active);


--
-- Name: ix_lightning_strikes_detected_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_lightning_strikes_detected_at ON public.lightning_strikes USING btree (detected_at);


--
-- Name: ix_locations_parent_location_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_locations_parent_location_id ON public.locations USING btree (parent_location_id);


--
-- Name: ix_locations_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_locations_tenant_id ON public.locations USING btree (tenant_id);


--
-- Name: ix_locations_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_locations_user_id ON public.locations USING btree (user_id);


--
-- Name: ix_notifications_alert_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_alert_id ON public.notifications USING btree (alert_id);


--
-- Name: ix_notifications_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_tenant_id ON public.notifications USING btree (tenant_id);


--
-- Name: ix_notifications_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_user_id ON public.notifications USING btree (user_id);


--
-- Name: ix_push_subscriptions_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_push_subscriptions_tenant_id ON public.push_subscriptions USING btree (tenant_id);


--
-- Name: ix_push_subscriptions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_push_subscriptions_user_id ON public.push_subscriptions USING btree (user_id);


--
-- Name: ix_radar_frames_captured_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_radar_frames_captured_at ON public.radar_frames USING btree (captured_at);


--
-- Name: ix_radar_frames_weather_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_radar_frames_weather_source_id ON public.radar_frames USING btree (weather_source_id);


--
-- Name: ix_satellite_images_captured_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_satellite_images_captured_at ON public.satellite_images USING btree (captured_at);


--
-- Name: ix_storm_cells_detected_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storm_cells_detected_at ON public.storm_cells USING btree (detected_at);


--
-- Name: ix_storm_cells_weather_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storm_cells_weather_source_id ON public.storm_cells USING btree (weather_source_id);


--
-- Name: ix_storm_observations_observed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storm_observations_observed_at ON public.storm_observations USING btree (observed_at);


--
-- Name: ix_storm_observations_storm_track_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storm_observations_storm_track_id ON public.storm_observations USING btree (storm_track_id);


--
-- Name: ix_storm_risks_computed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storm_risks_computed_at ON public.storm_risks USING btree (computed_at);


--
-- Name: ix_storm_risks_location_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storm_risks_location_id ON public.storm_risks USING btree (location_id);


--
-- Name: ix_storm_risks_storm_cell_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storm_risks_storm_cell_id ON public.storm_risks USING btree (storm_cell_id);


--
-- Name: ix_storm_risks_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storm_risks_tenant_id ON public.storm_risks USING btree (tenant_id);


--
-- Name: ix_storm_tracks_storm_cell_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_storm_tracks_storm_cell_id ON public.storm_tracks USING btree (storm_cell_id);


--
-- Name: ix_tenants_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_tenants_slug ON public.tenants USING btree (slug);


--
-- Name: ix_user_reports_reported_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_reports_reported_at ON public.user_reports USING btree (reported_at);


--
-- Name: ix_user_reports_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_reports_tenant_id ON public.user_reports USING btree (tenant_id);


--
-- Name: ix_user_reports_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_reports_user_id ON public.user_reports USING btree (user_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_google_sub; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_google_sub ON public.users USING btree (google_sub);


--
-- Name: ix_users_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_tenant_id ON public.users USING btree (tenant_id);


--
-- Name: alert_preferences alert_preferences_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alert_preferences
    ADD CONSTRAINT alert_preferences_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id) ON DELETE CASCADE;


--
-- Name: alerts alerts_convective_watch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_convective_watch_id_fkey FOREIGN KEY (convective_watch_id) REFERENCES public.convective_watches(id) ON DELETE SET NULL;


--
-- Name: alerts alerts_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id) ON DELETE CASCADE;


--
-- Name: alerts alerts_storm_cell_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_storm_cell_id_fkey FOREIGN KEY (storm_cell_id) REFERENCES public.storm_cells(id) ON DELETE SET NULL;


--
-- Name: alerts alerts_storm_risk_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_storm_risk_id_fkey FOREIGN KEY (storm_risk_id) REFERENCES public.storm_risks(id) ON DELETE SET NULL;


--
-- Name: alerts alerts_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: alerts alerts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: locations locations_parent_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_parent_location_id_fkey FOREIGN KEY (parent_location_id) REFERENCES public.locations(id) ON DELETE CASCADE;


--
-- Name: locations locations_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: locations locations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations
    ADD CONSTRAINT locations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_alert_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_alert_id_fkey FOREIGN KEY (alert_id) REFERENCES public.alerts(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: notifications notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: push_subscriptions push_subscriptions_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: push_subscriptions push_subscriptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.push_subscriptions
    ADD CONSTRAINT push_subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: radar_frames radar_frames_weather_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.radar_frames
    ADD CONSTRAINT radar_frames_weather_source_id_fkey FOREIGN KEY (weather_source_id) REFERENCES public.weather_sources(id) ON DELETE CASCADE;


--
-- Name: storm_cells storm_cells_weather_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storm_cells
    ADD CONSTRAINT storm_cells_weather_source_id_fkey FOREIGN KEY (weather_source_id) REFERENCES public.weather_sources(id) ON DELETE SET NULL;


--
-- Name: storm_observations storm_observations_storm_track_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storm_observations
    ADD CONSTRAINT storm_observations_storm_track_id_fkey FOREIGN KEY (storm_track_id) REFERENCES public.storm_tracks(id) ON DELETE CASCADE;


--
-- Name: storm_risks storm_risks_location_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storm_risks
    ADD CONSTRAINT storm_risks_location_id_fkey FOREIGN KEY (location_id) REFERENCES public.locations(id) ON DELETE CASCADE;


--
-- Name: storm_risks storm_risks_storm_cell_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storm_risks
    ADD CONSTRAINT storm_risks_storm_cell_id_fkey FOREIGN KEY (storm_cell_id) REFERENCES public.storm_cells(id) ON DELETE SET NULL;


--
-- Name: storm_risks storm_risks_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storm_risks
    ADD CONSTRAINT storm_risks_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: storm_tracks storm_tracks_storm_cell_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storm_tracks
    ADD CONSTRAINT storm_tracks_storm_cell_id_fkey FOREIGN KEY (storm_cell_id) REFERENCES public.storm_cells(id) ON DELETE CASCADE;


--
-- Name: user_reports user_reports_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_reports
    ADD CONSTRAINT user_reports_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: user_reports user_reports_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_reports
    ADD CONSTRAINT user_reports_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users users_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

