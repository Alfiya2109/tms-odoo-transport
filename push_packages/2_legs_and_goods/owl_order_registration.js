/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const { Component, useState, useRef, onMounted, onWillUnmount, onWillStart } = owl;

export class OwlOrderRegistration extends Component {
    static template = "transport_management_new.OwlOrderRegistration";
    static props = ["action", "actionId", "className", "globalState", "state"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.dialogService = useService("dialog");
        this.mapContainer = useRef("mapContainer");

        this.map = null;
        this.routePolyline = null;
        this.markers = [];
        this.previewTimer = null;

        // Initialize state
        this.state = useState({
            customer_id: "",
            order_contact_id: "",
            order_reference: "",
            project_code: "",
            transport_order_type_id: "",
            freight_service_id: "",
            goods_profile_id: "",
            template_id: "",
            company_id: "",
            map_picking_mode: null,
            sender_expanded: false,
            receiver_expanded: false,

             // Addresses (Priced leg)
            sender_address_id: null,
            sender_name: "",
            sender_street: "",
            sender_street_2: "",
            sender_city: "",
            sender_state_id: null,
            sender_zip: "",
            sender_country_id: null,
            sender_latitude: 0.0,
            sender_longitude: 0.0,
            sender_phone: "",
            sender_mobile: "",
            sender_email: "",
            sender_contact_person: "",
            sender_contact_phone: "",
            sender_access_instructions: "",
            sender_price_zone_id: "",

            receiver_address_id: null,
            receiver_name: "",
            receiver_street: "",
            receiver_street_2: "",
            receiver_city: "",
            receiver_state_id: null,
            receiver_zip: "",
            receiver_country_id: null,
            receiver_latitude: 0.0,
            receiver_longitude: 0.0,
            receiver_phone: "",
            receiver_mobile: "",
            receiver_email: "",
            receiver_contact_person: "",
            receiver_contact_phone: "",
            receiver_access_instructions: "",
            receiver_price_zone_id: "",

            // Consignment reference layer
            is_successive_carriage: false,
            consignment_origin_address_id: null,
            consignment_origin_name: "",
            consignment_origin_street: "",
            consignment_origin_street_2: "",
            consignment_origin_city: "",
            consignment_origin_state_id: null,
            consignment_origin_zip: "",
            consignment_origin_country_id: null,
            consignment_origin_latitude: 0.0,
            consignment_origin_longitude: 0.0,

            consignment_destination_address_id: null,
            consignment_destination_name: "",
            consignment_destination_street: "",
            consignment_destination_street_2: "",
            consignment_destination_city: "",
            consignment_destination_state_id: null,
            consignment_destination_zip: "",
            consignment_destination_country_id: null,
            consignment_destination_latitude: 0.0,
            consignment_destination_longitude: 0.0,

            consignment_sender_id: null,
            consignment_consignee_id: null,
            consignment_waybill_number: "",
            ordering_carrier_id: null,

            // Schedule & priority
            pick_up_date: new Date().toISOString().split('T')[0],
            pick_up_time_window: "08:00-12:00",
            pick_up_time_from: "",
            pick_up_time_to: "",
            estimated_pickup_duration: 30,
            priority: "0",
            delivery_date: new Date().toISOString().split('T')[0],
            delivery_time_window: "13:00-17:00",
            delivery_time_from: "",
            delivery_time_to: "",
            estimatedTimeOfDelivery: "",
            estimated_delivery_duration: 30,
            incoterm_id: "",
            incoterm_location: "",

            // Planning & route
            planning_type: "direct",
            showLegEditor: false,
            legEditor: {
                idx: null,
                type_id: "",
                carrier_id: "",
                from: "",
                to: "",
                cost: 0.0
            },

            // Lines & charges
            goods_lines: [],
            charges: [], // Holds manual charges
            system_charges: [], // Holds contract computed charges returned by preview

            // Notes
            goods_description: "",
            invoice_reference: "",
            internal_details: "",
            external_details: "",
            invoicing_instructions: "",

            // Compliance & COD fields
            commissionnaire_id: "",
            cod_amount: 0.0,
            cod_currency_id: "",
            hazmat_emergency_phone: "",

            // Requirements
            require_delivery_photo: true,
            require_delivery_signature: true,
            requirement_ids: [],

            // computed totals & margin (updated via preview)
            total_gross_weight: 0,
            total_volume: 0,
            total_ldm: 0,
            total_billable_weight: 0,
            margin_revenue: 0,
            margin_cost: 0,
            margin_amount: 0,
            margin_percent: 0,
            legs: [],
            preview_error: "",

            // Master data lists
            customers: [],
            contacts: [],
            order_types: [],
            freight_services: [],
            goods_profiles: [],
            templates: [],
            package_types: [],
            incoterms: [],
            adr_substances: [],
            material_types: [],
            companies: [],
            states: [],
            countries: [],
            requirements: [],
            price_zones: [],
            partners: [],
            currencies: [],
            products: [],
            price_types: [],
            is_charges_customized: false,
            container_types: [],
            nmfc_classes: [],

            // Address Search dropdown
            activeDdn: null,
            searchKeyword: "",
            searchResults: [],

            // Custom Import Address Modal
            showImportAddressModal: null, // "sender" or "receiver"
            importSearchQuery: "",
            oftenUsedAddresses: [],
            transportHubs: [],
            addressBookResults: [],

            // UI states
            showGoodsEditor: false,
            showChargeForm: false,
            editing_id: null,
        });

        this.goodsEditor = useState({
            idx: null,
            type: "Goods",
            package_id: "",
            goods_label: "",
            description: "",
            quantity: 1,
            length: 120,
            width: 80,
            height: 160,
            volume_compute_method: "manual",
            volume_manual: 0.0,
            volume_m3: 0.0,
            ldm_compute_method: "manual",
            ldm_manual: 0.0,
            ldm: 0.0,
            stackable: true,
            stacking_factor: 1.0,
            gross_weight: 100,
            volumetric_weight: 0.0,
            billable_weight: 100,
            package_type_id: "",
            is_dangerous_goods: false,
            adr_substance_id: "",
            adr_description: "",
            net_explosive_mass: 0.0,
            adr_limited_quantity: false,
            environmentally_hazardous: false,
            temperature_min: "",
            temperature_max: "",
            material_type_id: "",
            waste_code: "",
            container_type_id: "",
            container_number: "",
            container_seal_number: "",
            container_tare_weight: 0.0,
            volume_liters: 0.0,
            liquid_density: 0.0,
            liquid_product_name: "",
            nmfc_class_manual: false,
            nmfc_class_id: "",
            showAdr: false,
            showTemp: false,
            showContainer: false,
            showLiquid: false,
            showMaterial: false,
            showNmfc: false,
        });

        this.chargeEditor = useState({
            kind: "Custom (manual)",
            desc: "",
            amt: 500,
        });

        // Load master data on startup
        onWillStart(async () => {
            await this.loadMasterData();
        });

        onMounted(() => {
            this.initializeMap();
            this.triggerPreview();
        });

        onWillUnmount(() => {
            this.map?.remove();
        });
    }

    get selectedGoodsProfile() {
        const profileId = parseInt(this.state.goods_profile_id);
        return this.state.goods_profiles.find(g => g.id === profileId) || {};
    }

    // ── Manual Leg Operations ─────────────────────────────────────────
    openLegEditor(idx = null) {
        if (idx === null) {
            this.state.legEditor = {
                idx: null,
                type_id: this.state.transport_types[0]?.id || "",
                carrier_id: this.state.carriers[0]?.id || "",
                from: "",
                to: "",
                cost: 0.0
            };
        } else {
            const leg = this.state.legs[idx];
            // Find type and carrier IDs
            const tType = this.state.transport_types.find(t => t.code === leg.type);
            const tCarrier = this.state.carriers.find(c => c.partner_id[0] === leg.carrier_id);
            this.state.legEditor = {
                idx: idx,
                type_id: tType ? tType.id : (leg.type_id || ""),
                carrier_id: tCarrier ? tCarrier.id : (leg.carrier_id || ""),
                from: leg.from || "",
                to: leg.to || "",
                cost: leg.cost || 0.0
            };
        }
        this.state.showLegEditor = true;
    }

    async saveLegRow() {
        const typeId = parseInt(this.state.legEditor.type_id);
        const carrierId = parseInt(this.state.legEditor.carrier_id);
        
        const selectedType = this.state.transport_types.find(t => t.id === typeId);
        const selectedCarrier = this.state.carriers.find(c => c.id === carrierId);

        const legData = {
            id: this.state.legEditor.idx !== null ? this.state.legs[this.state.legEditor.idx].id : null,
            sequence: this.state.legEditor.idx !== null ? (this.state.legEditor.idx + 1) : (this.state.legs.length + 1),
            type: selectedType ? selectedType.code : "DI",
            type_id: typeId,
            from: this.state.legEditor.from,
            to: this.state.legEditor.to,
            carrier: selectedCarrier ? selectedCarrier.name : "Own fleet",
            carrier_id: selectedCarrier ? selectedCarrier.partner_id[0] : false,
            cost: parseFloat(this.state.legEditor.cost || 0.0),
            is_manual: true
        };

        if (this.state.legEditor.idx === null) {
            this.state.legs.push(legData);
        } else {
            this.state.legs[this.state.legEditor.idx] = legData;
        }

        this.state.showLegEditor = false;
        await this.runPreview();
    }

    async deleteLegRow(idx) {
        this.state.legs.splice(idx, 1);
        // re-sequence remaining
        this.state.legs.forEach((l, i) => {
            l.sequence = i + 1;
        });
        await this.runPreview();
    }

    // ── Master Data Loading ──────────────────────────────────────────
    async loadMasterData() {
        try {
            // Load companies
            this.state.companies = await this.orm.searchRead("res.company", [], ["id", "name", "currency_id", "hazmat_emergency_phone"]);
            this.state.company_id = this.state.companies[0]?.id || "";

            const firstCompany = this.state.companies[0];
            if (firstCompany) {
                this.state.hazmat_emergency_phone = firstCompany.hazmat_emergency_phone || "";
                this.state.cod_currency_id = firstCompany.currency_id ? firstCompany.currency_id[0] : "";
            }

            // Load customers based on active company
            await this.loadCustomersForCompany(this.state.company_id);

            this.state.order_types = await this.orm.searchRead("transport.order.type", [], ["id", "name", "goods_profile_id", "default_planning_type"]);
            const firstType = this.state.order_types[0];
            if (firstType) {
                this.state.transport_order_type_id = firstType.id;
                this.state.planning_type = firstType.default_planning_type || 'direct';
            }

            this.state.freight_services = await this.orm.searchRead("freight.service", [], ["id", "name"]);
            this.state.freight_service_id = this.state.freight_services[0]?.id || "";

            this.state.goods_profiles = await this.orm.searchRead("goods.profile", [], [
                "id", 
                "name", 
                "show_package_id", 
                "show_goods_label", 
                "show_description", 
                "show_quantity", 
                "show_package_type", 
                "show_dimensions", 
                "show_stacking", 
                "show_volume", 
                "show_ldm", 
                "show_gross_weight", 
                "show_volumetric_weight", 
                "show_billable_weight", 
                "show_adr", 
                "show_container", 
                "show_liquid", 
                "show_temperature", 
                "show_material_type", 
                "show_nmfc", 
                "show_imperial_units"
            ]);
            let defaultProfileId = "";
            if (firstType && firstType.goods_profile_id) {
                defaultProfileId = Array.isArray(firstType.goods_profile_id)
                    ? firstType.goods_profile_id[0]
                    : firstType.goods_profile_id;
            } else {
                defaultProfileId = this.state.goods_profiles[0]?.id || "";
            }
            this.state.goods_profile_id = defaultProfileId;
 
            this.state.templates = await this.orm.searchRead("transport.order.template", [], ["id", "name"]);
            this.state.package_types = await this.orm.searchRead("package.type", [], ["id", "name", "ldm_per_unit"]);
            this.state.incoterms = await this.orm.searchRead("account.incoterms", [], ["id", "name", "code"]);
            this.state.adr_substances = await this.orm.searchRead("adr.substance", [], ["id", "display_name", "un_number"]);
            this.state.material_types = await this.orm.searchRead("transport.material.type", [], ["id", "name"]);
            this.state.container_types = await this.orm.searchRead("container.type", [], ["id", "name", "code", "tare_weight_kg"]);
            this.state.nmfc_classes = await this.orm.searchRead("freight.nmfc.class", [], ["id", "code", "name"]);

            this.state.states = await this.orm.searchRead("res.country.state", [], ["id", "display_name"]);
            this.state.countries = await this.orm.searchRead("res.country", [], ["id", "display_name", "code"]);
            this.state.requirements = await this.orm.searchRead("transport.requirement", [], ["id", "name"]);
            this.state.price_zones = await this.orm.searchRead("transport.price.zone", [], ["id", "name"]);
            this.state.currencies = await this.orm.searchRead("res.currency", [["active", "=", true]], ["id", "name"]);
            this.state.partners = await this.orm.searchRead("res.partner", [["is_company", "=", true]], ["id", "name"]);
            this.state.products = await this.orm.searchRead("product.product", [["type", "=", "service"]], ["id", "name"]);
            this.state.transport_types = await this.orm.searchRead("transport.type", [], ["id", "name", "code"]);
            this.state.carriers = await this.orm.searchRead("transport.carrier", [], ["id", "name", "partner_id"]);
            this.state.price_types = [
                { id: 'price_per_order', name: 'Price per order' },
                { id: 'price_per_weight_unit', name: 'Price per weight unit' },
                { id: 'price_per_distance_unit', name: 'Price per distance unit' },
                { id: 'price_per_volume_unit', name: 'Price per volume unit' },
                { id: 'price_per_ldm_unit', name: 'Price per LDM unit' },
                { id: 'price_per_gross_weight_unit', name: 'Price per gross weight unit' },
                { id: 'price_per_hour_unit', name: 'Price per hour' }
            ];
        } catch (err) {
            console.error("Error loading master data: ", err);
        }
    }

    async loadCustomersForCompany(companyId) {
        if (!companyId) {
            this.state.customers = [];
            return;
        }
        try {
            const transportCustomers = await this.orm.searchRead(
                "transport.customer",
                [["company_ids", "in", [parseInt(companyId)]]],
                ["partner_id"]
            );
            const partnerIds = transportCustomers.map(tc => tc.partner_id[0]).filter(Boolean);
            if (partnerIds.length > 0) {
                this.state.customers = await this.orm.searchRead(
                    "res.partner",
                    [["id", "in", partnerIds]],
                    ["id", "name"]
                );
            } else {
                this.state.customers = [];
            }
        } catch (e) {
            console.error("Failed to load customers for company: ", e);
            // fallback
            this.state.customers = await this.orm.searchRead("res.partner", [], ["id", "name"], { limit: 80 });
        }
    }

    async onCompanySelectChange(ev) {
        const val = ev.target.value;
        this.state.company_id = val;
        
        const comp = this.state.companies.find(c => c.id === parseInt(val));
        if (comp) {
            this.state.hazmat_emergency_phone = comp.hazmat_emergency_phone || "";
            this.state.cod_currency_id = comp.currency_id ? comp.currency_id[0] : "";
        }

        await this.loadCustomersForCompany(val);
        this.triggerPreview();
    }

    async onOrderTypeSelectChange(ev) {
        const val = ev.target.value;
        if (val === "search_more") {
            ev.target.value = this.state.transport_order_type_id;
            await this.onCreateOrderType();
        } else {
            const orderTypeId = parseInt(val);
            this.state.transport_order_type_id = orderTypeId;
            const selectedType = this.state.order_types.find(ot => ot.id === orderTypeId);
            if (selectedType && selectedType.goods_profile_id) {
                const profileId = Array.isArray(selectedType.goods_profile_id)
                    ? selectedType.goods_profile_id[0]
                    : selectedType.goods_profile_id;
                this.state.goods_profile_id = profileId;
            }
            if (selectedType && selectedType.default_planning_type) {
                this.state.planning_type = selectedType.default_planning_type;
            } else {
                this.state.planning_type = 'direct';
            }
            this.triggerPreview();
        }
    }

    async onFreightServiceSelectChange(ev) {
        const val = ev.target.value;
        if (val === "search_more") {
            ev.target.value = this.state.freight_service_id;
            await this.onCreateFreightService();
        } else {
            this.state.freight_service_id = parseInt(val);
            this.triggerPreview();
        }
    }

    // ── Contacts (child contacts of the selected customer) ───────────
    async loadContacts(customerId) {
        if (!customerId) {
            this.state.contacts = [];
            return;
        }
        try {
            // Mirror the order_contact_id domain on transport.order:
            // child contacts of the customer that are individuals.
            this.state.contacts = await this.orm.searchRead(
                "res.partner",
                [["id", "child_of", parseInt(customerId)], ["is_company", "=", false]],
                ["id", "name", "phone", "email"]
            );
        } catch (e) {
            console.error("Failed to load contacts for customer: ", e);
            this.state.contacts = [];
        }
    }

    async onCustomerSelectChange(ev) {
        const val = ev.target.value;
        if (val === "search_more") {
            ev.target.value = this.state.customer_id;
            await this.onSearchCustomerDialog();
        } else {
            this.state.customer_id = val;
            this.state.order_contact_id = "";
            await this.loadContacts(val);
            this.triggerPreview();
        }
    }

    async onSearchCustomerDialog() {
        let partnerIds = [];
        try {
            const transportCustomers = await this.orm.searchRead(
                "transport.customer",
                [["company_ids", "in", [parseInt(this.state.company_id)]]],
                ["partner_id"]
            );
            partnerIds = transportCustomers.map(tc => tc.partner_id[0]).filter(Boolean);
        } catch (e) {
            console.error("Failed to load transport customers: ", e);
        }

        const domain = partnerIds.length > 0 ? [["id", "in", partnerIds]] : [["is_company", "=", true]];

        this.dialogService.add(SelectCreateDialog, {
            resModel: "res.partner",
            title: _t("Search: Customer"),
            multiSelect: false,
            noCreate: false,
            domain: domain,
            context: {
                default_is_company: true,
            },
            onSelected: async (selectedIds) => {
                if (selectedIds && selectedIds.length > 0) {
                    const selectedId = selectedIds[0];
                    await this.loadCustomersForCompany(this.state.company_id);
                    this.state.customer_id = selectedId;
                    this.state.order_contact_id = "";
                    await this.loadContacts(selectedId);
                    this.triggerPreview();
                }
            }
        });
    }

    // ── Map Integration ──────────────────────────────────────────────
    initializeMap() {
        if (this.mapContainer.el && !this.map) {
            // Default center Sweden
            this.map = L.map(this.mapContainer.el).setView([59.3293, 18.0686], 5);
            L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19,
                attribution: "&copy; OpenStreetMap contributors",
            }).addTo(this.map);

            this.map.on("click", async (e) => {
                if (this.state.map_picking_mode) {
                    const type = this.state.map_picking_mode;
                    const lat = e.latlng.lat.toFixed(6);
                    const lng = e.latlng.lng.toFixed(6);

                    this.state[type + "_latitude"] = lat;
                    this.state[type + "_longitude"] = lng;

                    this.notification.add(_t(`Coordinates selected: ${lat}, ${lng}`), { type: "info" });
                    this.state.map_picking_mode = null;

                    this.updateMapRoute();
                    this.triggerPreview();

                    try {
                        const url = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json`;
                        const res = await fetch(url);
                        const data = await res.json();
                        if (data && data.address) {
                            this.state[type + "_street"] = data.address.road || data.address.suburb || data.address.neighbourhood || "";
                            this.state[type + "_city"] = data.address.city || data.address.town || data.address.village || "";
                            this.state[type + "_zip"] = data.address.postcode || "";

                            if (data.address.country_code) {
                                const cc = data.address.country_code.toUpperCase();
                                const country = this.state.countries.find(c => c.code && c.code.toUpperCase() === cc);
                                if (country) {
                                    this.state[type + "_country_id"] = country.id;
                                }
                            }
                        }
                    } catch (err) {
                        console.error("Reverse geocoding failed: ", err);
                    }
                }
            });

            this.updateMapRoute();
        }
    }

    updateMapRoute() {
        if (!this.map) return;

        // Clear existing markers
        this.markers.forEach(m => m.remove());
        this.markers = [];
        if (this.routePolyline) {
            this.routePolyline.remove();
            this.routePolyline = null;
        }

        const points = [];
        const addMarker = (lat, lng, color, label) => {
            if (lat && lng) {
                const marker = L.marker([lat, lng], {
                    icon: L.divIcon({
                        className: 'custom-map-marker',
                        html: `
                            <div style="position: relative; width: 24px; height: 24px;">
                                <svg viewBox="0 0 24 24" fill="${color}" stroke="white" stroke-width="2" style="width: 24px; height: 24px;">
                                    <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/>
                                </svg>
                                <div style="position: absolute; top: 3px; left: 0; right: 0; text-align: center; color: white; font-weight: bold; font-size: 8px;">
                                    ${label}
                                </div>
                            </div>`,
                        iconSize: [24, 24],
                        iconAnchor: [12, 24],
                    })
                }).addTo(this.map);
                this.markers.push(marker);
                points.push([lat, lng]);
            }
        };

        addMarker(this.state.sender_latitude, this.state.sender_longitude, "#378ADD", "S");
        addMarker(this.state.receiver_latitude, this.state.receiver_longitude, "#1D9E75", "D");

        if (points.length === 2) {
            this.routePolyline = L.polyline(points, {
                color: '#378ADD',
                weight: 3,
                dashArray: '5, 6'
            }).addTo(this.map);
            this.map.fitBounds(points, { padding: [40, 40] });
        }
    }

    // ── Live Calculation Trigger ─────────────────────────────────────
    triggerPreview() {
        clearTimeout(this.previewTimer);
        this.previewTimer = setTimeout(() => this.runPreview(), 500);
    }

    async runPreview() {
        const payload = this.getPayload();
        // Skip preview if basic fields are missing to avoid Odoo validate exceptions
        if (!payload.customer_id || !payload.sender_country_id || !payload.receiver_country_id) {
            return;
        }

        try {
            const res = await this.orm.call(
                "transport.order",
                "preview_booking",
                [payload]
            );

            if (res && res.success) {
                // Update computed totals
                this.state.total_gross_weight = res.totals.total_gross_weight;
                this.state.total_volume = res.totals.total_volume;
                this.state.total_ldm = res.totals.total_ldm;
                this.state.total_billable_weight = res.totals.total_billable_weight;

                if (!this.state.is_charges_customized) {
                    this.state.charges = res.charges;
                }
                this.state.legs = res.legs;
                this.state.preview_error = "";

                if (this.state.is_charges_customized) {
                    this.state.margin_revenue = this.state.charges.reduce((sum, c) => sum + (parseFloat(c.quantity || 0) * parseFloat(c.price_per_unit || 0)), 0);
                    this.state.margin_cost = res.margin.cost;
                    this.state.margin_amount = this.state.margin_revenue - this.state.margin_cost;
                    this.state.margin_percent = this.state.margin_revenue > 0 ? (this.state.margin_amount / this.state.margin_revenue * 100.0) : 0.0;
                } else {
                    this.state.margin_revenue = res.margin.revenue;
                    this.state.margin_cost = res.margin.cost;
                    this.state.margin_amount = res.margin.margin;
                    this.state.margin_percent = res.margin.margin_percent;
                }
            } else if (res && !res.success) {
                this.state.legs = [];
                this.state.preview_error = res.error || "Failed to calculate booking preview.";
            }
        } catch (err) {
            console.error("Preview booking failed: ", err);
            this.state.legs = [];
            this.state.preview_error = err.message || err.toString() || "Server error while calculating preview.";
        }
    }

    getPayload() {
        return {
            customer_id: this.state.customer_id,
            order_contact_id: this.state.order_contact_id,
            order_reference: this.state.order_reference,
            project_code: this.state.project_code,
            transport_order_type_id: this.state.transport_order_type_id,
            freight_service_id: this.state.freight_service_id,
            goods_profile_id: this.state.goods_profile_id,
            template_id: this.state.template_id,
            company_id: this.state.company_id,

            sender_address_id: this.state.sender_address_id,
            sender_name: this.state.sender_name,
            sender_street: this.state.sender_street,
            sender_street_2: this.state.sender_street_2,
            sender_city: this.state.sender_city,
            sender_state_id: this.state.sender_state_id,
            sender_zip: this.state.sender_zip,
            sender_country_id: this.state.sender_country_id,
            sender_latitude: this.state.sender_latitude,
            sender_longitude: this.state.sender_longitude,
            sender_phone: this.state.sender_phone,
            sender_mobile: this.state.sender_mobile,
            sender_email: this.state.sender_email,
            sender_contact_person: this.state.sender_contact_person,
            sender_contact_phone: this.state.sender_contact_phone,
            sender_access_instructions: this.state.sender_access_instructions,
            sender_price_zone_id: this.state.sender_price_zone_id,

            receiver_address_id: this.state.receiver_address_id,
            receiver_name: this.state.receiver_name,
            receiver_street: this.state.receiver_street,
            receiver_street_2: this.state.receiver_street_2,
            receiver_city: this.state.receiver_city,
            receiver_state_id: this.state.receiver_state_id,
            receiver_zip: this.state.receiver_zip,
            receiver_country_id: this.state.receiver_country_id,
            receiver_latitude: this.state.receiver_latitude,
            receiver_longitude: this.state.receiver_longitude,
            receiver_phone: this.state.receiver_phone,
            receiver_mobile: this.state.receiver_mobile,
            receiver_email: this.state.receiver_email,
            receiver_contact_person: this.state.receiver_contact_person,
            receiver_contact_phone: this.state.receiver_contact_phone,
            receiver_access_instructions: this.state.receiver_access_instructions,
            receiver_price_zone_id: this.state.receiver_price_zone_id,

            consignment_origin_address_id: this.state.consignment_origin_address_id,
            consignment_origin_name: this.state.consignment_origin_name,
            consignment_origin_street: this.state.consignment_origin_street,
            consignment_origin_street_2: this.state.consignment_origin_street_2,
            consignment_origin_city: this.state.consignment_origin_city,
            consignment_origin_state_id: this.state.consignment_origin_state_id,
            consignment_origin_zip: this.state.consignment_origin_zip,
            consignment_origin_country_id: this.state.consignment_origin_country_id,
            consignment_origin_latitude: this.state.consignment_origin_latitude,
            consignment_origin_longitude: this.state.consignment_origin_longitude,

            consignment_destination_address_id: this.state.consignment_destination_address_id,
            consignment_destination_name: this.state.consignment_destination_name,
            consignment_destination_street: this.state.consignment_destination_street,
            consignment_destination_street_2: this.state.consignment_destination_street_2,
            consignment_destination_city: this.state.consignment_destination_city,
            consignment_destination_state_id: this.state.consignment_destination_state_id,
            consignment_destination_zip: this.state.consignment_destination_zip,
            consignment_destination_country_id: this.state.consignment_destination_country_id,
            consignment_destination_latitude: this.state.consignment_destination_latitude,
            consignment_destination_longitude: this.state.consignment_destination_longitude,

            consignment_sender_id: this.state.consignment_sender_id,
            consignment_consignee_id: this.state.consignment_consignee_id,
            consignment_waybill_number: this.state.consignment_waybill_number,
            ordering_carrier_id: this.state.ordering_carrier_id,
            is_successive_carriage: this.state.is_successive_carriage,

            pick_up_date: this.state.pick_up_date,
            pick_up_time_window: this.state.pick_up_time_window,
            pick_up_time_from: this.state.pick_up_time_from,
            pick_up_time_to: this.state.pick_up_time_to,
            estimated_pickup_duration: this.state.estimated_pickup_duration,
            priority: this.state.priority,
            delivery_date: this.state.delivery_date,
            delivery_time_window: this.state.delivery_time_window,
            delivery_time_from: this.state.delivery_time_from,
            delivery_time_to: this.state.delivery_time_to,
            estimatedTimeOfDelivery: this.state.estimatedTimeOfDelivery,
            estimated_delivery_duration: this.state.estimated_delivery_duration,
            incoterm_id: this.state.incoterm_id,
            incoterm_location: this.state.incoterm_location,

            planning_type: this.state.planning_type,
            goods_lines: this.state.goods_lines,
            charges: this.state.charges,
            legs: this.state.legs,

            goods_description: this.state.goods_description,
            invoice_reference: this.state.invoice_reference,
            internal_details: this.state.internal_details,
            external_details: this.state.external_details,
            invoicing_instructions: this.state.invoicing_instructions,

            commissionnaire_id: this.state.commissionnaire_id,
            cod_amount: this.state.cod_amount,
            cod_currency_id: this.state.cod_currency_id,
            hazmat_emergency_phone: this.state.hazmat_emergency_phone,

            require_delivery_photo: this.state.require_delivery_photo,
            require_delivery_signature: this.state.require_delivery_signature,
            requirement_ids: this.state.requirement_ids,
        };
    }

    // ── Address Autocomplete Search ──────────────────────────────────
    async onAddressSearch(type, keyword) {
        this.state.searchKeyword = keyword;
        this.state.activeDdn = type;

        if (keyword.length < 2) {
            this.state.searchResults = [];
            return;
        }

        try {
            const results = await this.orm.searchRead(
                "res.partner",
                ["|", "|", ["name", "ilike", keyword], ["city", "ilike", keyword], ["zip", "ilike", keyword]],
                ["name", "street", "street2", "city", "zip", "country_id", "state_id", "partner_latitude", "partner_longitude", "phone", "mobile", "email", "access_instructions"],
                { limit: 6 }
            );
            this.state.searchResults = results;
        } catch (e) {
            console.error("Address search failed: ", e);
        }
    }

    onPickAddress(type, partner) {
        this.state[type + "_address_id"] = partner.id;
        this.state[type + "_name"] = partner.name || "";
        this.state[type + "_street"] = partner.street || "";
        this.state[type + "_street_2"] = partner.street2 || "";
        this.state[type + "_city"] = partner.city || "";
        this.state[type + "_zip"] = partner.zip || "";
        this.state[type + "_state_id"] = partner.state_id ? partner.state_id[0] : null;
        this.state[type + "_country_id"] = partner.country_id ? partner.country_id[0] : null;
        this.state[type + "_latitude"] = partner.partner_latitude || 0.0;
        this.state[type + "_longitude"] = partner.partner_longitude || 0.0;
        this.state[type + "_phone"] = partner.phone || "";
        this.state[type + "_mobile"] = partner.mobile || "";
        this.state[type + "_email"] = partner.email || "";
        this.state[type + "_access_instructions"] = partner.access_instructions || "";

        if (type === "receiver") {
            this.mirrorReceiverToConsignment();
        }

        if (type === "sender") {
            this.state.sender_expanded = false;
        } else if (type === "receiver") {
            this.state.receiver_expanded = false;
        }

        this.state.activeDdn = null;
        this.state.searchKeyword = "";
        this.state.searchResults = [];

        this.updateMapRoute();
        this.triggerPreview();
    }

    onSwapAddresses() {
        const fields = ["address_id", "name", "street", "street_2", "zip", "city", "state_id", "country_id", "latitude", "longitude", "phone", "mobile", "email", "contact_person", "contact_phone", "access_instructions", "price_zone_id", "expanded"];
        fields.forEach(field => {
            const temp = this.state["sender_" + field];
            this.state["sender_" + field] = this.state["receiver_" + field];
            this.state["receiver_" + field] = temp;
        });
        this.mirrorReceiverToConsignment();
        this.updateMapRoute();
        this.triggerPreview();
    }

    async onGenerateLegs() {
        const payload = this.getPayload();
        if (!payload.customer_id) {
            this.notification.add(_t("Please select a Customer first."), { type: "danger" });
            return;
        }
        if (!payload.sender_country_id || !payload.receiver_country_id) {
            this.notification.add(_t("Please fill in Sender & Consignee address details first."), { type: "danger" });
            return;
        }
        this.notification.add(_t("Generating legs..."), { type: "info" });
        await this.runPreview();
    }

    onClearAddress(type) {
        this.state[type + "_address_id"] = null;
        this.state[type + "_name"] = "";
        this.state[type + "_street"] = "";
        this.state[type + "_street_2"] = "";
        this.state[type + "_city"] = "";
        this.state[type + "_zip"] = "";
        this.state[type + "_state_id"] = null;
        this.state[type + "_country_id"] = null;
        this.state[type + "_latitude"] = 0.0;
        this.state[type + "_longitude"] = 0.0;
        this.state[type + "_phone"] = "";
        this.state[type + "_mobile"] = "";
        this.state[type + "_email"] = "";
        this.state[type + "_contact_person"] = "";
        this.state[type + "_contact_phone"] = "";
        this.state[type + "_access_instructions"] = "";
        this.state[type + "_price_zone_id"] = "";

        this.updateMapRoute();
        this.triggerPreview();
    }

    mirrorReceiverToConsignment() {
        if (!this.state.is_successive_carriage) return;
        if (!this.state.consignment_destination_address_id) {
            this.state.consignment_destination_address_id = this.state.receiver_address_id;
            this.state.consignment_destination_name = this.state.receiver_name;
            this.state.consignment_destination_street = this.state.receiver_street;
            this.state.consignment_destination_street_2 = this.state.receiver_street_2;
            this.state.consignment_destination_city = this.state.receiver_city;
            this.state.consignment_destination_zip = this.state.receiver_zip;
            this.state.consignment_destination_state_id = this.state.receiver_state_id;
            this.state.consignment_destination_country_id = this.state.receiver_country_id;
            this.state.consignment_destination_latitude = this.state.receiver_latitude;
            this.state.consignment_destination_longitude = this.state.receiver_longitude;
        }
    }

    toggleConsignment() {
        this.state.is_successive_carriage = !this.state.is_successive_carriage;
        if (this.state.is_successive_carriage) {
            this.mirrorReceiverToConsignment();
        }
    }

    // ── Goods List Editor ───────────────────────────────────────────
    async generateSSCCBarcode() {
        try {
            const companyId = parseInt(this.state.company_id || this.state.companies[0]?.id || 0);
            if (!companyId) return;
            const barcode = await this.orm.call("sscc.number", "get_new_sscc_number", [companyId]);
            if (barcode) {
                this.goodsEditor.package_id = barcode;
            }
        } catch (err) {
            console.error("Failed to generate package ID: ", err);
        }
    }

    onGoodsDimensionsOrWeightsChange() {
        const qty = parseInt(this.goodsEditor.quantity || 1);
        const length = parseFloat(this.goodsEditor.length || 0.0);
        const width = parseFloat(this.goodsEditor.width || 0.0);
        const height = parseFloat(this.goodsEditor.height || 0.0);
        const stackable = this.goodsEditor.stackable;
        const sf = parseFloat(this.goodsEditor.stacking_factor || 1.0) || 1.0;

        // 1. Calculate Volume
        if (this.goodsEditor.volume_compute_method === 'dimensions') {
            const vol = (length / 100.0) * (width / 100.0) * (height / 100.0) * qty;
            this.goodsEditor.volume_m3 = stackable && sf > 1.0 ? vol / sf : vol;
        } else {
            this.goodsEditor.volume_m3 = parseFloat(this.goodsEditor.volume_manual || 0.0);
        }

        // 2. Calculate LDM
        if (this.goodsEditor.ldm_compute_method === 'pallet_rules') {
            const pkg = this.state.package_types.find(p => p.id === parseInt(this.goodsEditor.package_type_id));
            const ldmVal = qty * (pkg ? parseFloat(pkg.ldm_per_unit || 0.0) : 0.0);
            this.goodsEditor.ldm = stackable && sf > 1.0 ? ldmVal / sf : ldmVal;
        } else if (this.goodsEditor.ldm_compute_method === 'dimensions') {
            const baseLdm = ((length / 100.0) * (width / 100.0)) / 2.4;
            const ldmVal = baseLdm * qty;
            this.goodsEditor.ldm = stackable && sf > 1.0 ? ldmVal / sf : ldmVal;
        } else {
            this.goodsEditor.ldm = parseFloat(this.goodsEditor.ldm_manual || 0.0);
        }

        // 3. Volumetric Weight & Billable Weight
        this.goodsEditor.volumetric_weight = this.goodsEditor.volume_m3 * 250.0;
        this.goodsEditor.billable_weight = Math.max(parseFloat(this.goodsEditor.gross_weight || 0.0), this.goodsEditor.volumetric_weight);
    }

    openGoodsEditor(idx = null) {
        if (idx !== null) {
            const g = this.state.goods_lines[idx];
            Object.assign(this.goodsEditor, {
                idx: idx,
                type: g.type || "Goods",
                package_id: g.package_id || "",
                goods_label: g.goods_label || "",
                description: g.description || "",
                quantity: g.quantity || 1,
                length: g.length || 0,
                width: g.width || 0,
                height: g.height || 0,
                volume_compute_method: g.volume_compute_method || "manual",
                volume_manual: g.volume_manual || 0.0,
                volume_m3: g.volume_m3 || 0.0,
                ldm_compute_method: g.ldm_compute_method || "manual",
                ldm_manual: g.ldm_manual || 0.0,
                ldm: g.ldm || 0.0,
                stackable: g.stackable !== undefined ? g.stackable : true,
                stacking_factor: g.stacking_factor || 1.0,
                gross_weight: g.gross_weight || 0.0,
                volumetric_weight: g.volumetric_weight || 0.0,
                billable_weight: g.billable_weight || 0.0,
                package_type_id: g.package_type_id || "",
                is_dangerous_goods: g.is_dangerous_goods || false,
                adr_substance_id: g.adr_substance_id || "",
                adr_description: g.adr_description || "",
                net_explosive_mass: g.net_explosive_mass || 0.0,
                adr_limited_quantity: g.adr_limited_quantity || false,
                environmentally_hazardous: g.environmentally_hazardous || false,
                temperature_min: g.temperature_min || "",
                temperature_max: g.temperature_max || "",
                material_type_id: g.material_type_id || "",
                waste_code: g.waste_code || "",
                container_type_id: g.container_type_id || "",
                container_number: g.container_number || "",
                container_seal_number: g.container_seal_number || "",
                container_tare_weight: g.container_tare_weight || 0.0,
                volume_liters: g.volume_liters || 0.0,
                liquid_density: g.liquid_density || 0.0,
                liquid_product_name: g.liquid_product_name || "",
                nmfc_class_manual: g.nmfc_class_manual || false,
                nmfc_class_id: g.nmfc_class_id || "",
                showAdr: !!g.is_dangerous_goods,
                showTemp: g.temperature_min !== "" && g.temperature_min !== undefined && g.temperature_min !== null,
            });
        } else {
            const profile = this.selectedGoodsProfile;
            Object.assign(this.goodsEditor, {
                idx: null,
                type: "Goods",
                package_id: "",
                goods_label: "",
                description: "",
                quantity: 1,
                length: 0,
                width: 0,
                height: 0,
                volume_compute_method: profile.default_volume_compute_method || "manual",
                volume_manual: 0.0,
                volume_m3: 0.0,
                ldm_compute_method: profile.default_ldm_compute_method || "manual",
                ldm_manual: 0.0,
                ldm: 0.0,
                stackable: profile.default_stackable !== undefined ? profile.default_stackable : true,
                stacking_factor: 1.0,
                gross_weight: 0.0,
                volumetric_weight: 0.0,
                billable_weight: 0.0,
                package_type_id: this.state.package_types[0]?.id || "",
                is_dangerous_goods: false,
                adr_substance_id: "",
                adr_description: "",
                net_explosive_mass: 0.0,
                adr_limited_quantity: false,
                environmentally_hazardous: false,
                temperature_min: "",
                temperature_max: "",
                material_type_id: "",
                waste_code: "",
                container_type_id: "",
                container_number: "",
                container_seal_number: "",
                container_tare_weight: 0.0,
                volume_liters: 0.0,
                liquid_density: 0.0,
                liquid_product_name: "",
                nmfc_class_manual: false,
                nmfc_class_id: "",
                showAdr: false,
                showTemp: false,
            });
        }
        this.state.showGoodsEditor = true;
        this.onGoodsDimensionsOrWeightsChange();
    }

    saveGoodsRow() {
        const row = {
            type: this.goodsEditor.type,
            package_id: this.goodsEditor.package_id,
            goods_label: this.goodsEditor.goods_label || this.goodsEditor.description,
            description: this.goodsEditor.description,
            quantity: parseInt(this.goodsEditor.quantity) || 1,
            length: parseFloat(this.goodsEditor.length) || 0.0,
            width: parseFloat(this.goodsEditor.width) || 0.0,
            height: parseFloat(this.goodsEditor.height) || 0.0,
            volume_compute_method: this.goodsEditor.volume_compute_method,
            volume_manual: parseFloat(this.goodsEditor.volume_manual) || 0.0,
            volume_m3: parseFloat(this.goodsEditor.volume_m3) || 0.0,
            ldm_compute_method: this.goodsEditor.ldm_compute_method,
            ldm_manual: parseFloat(this.goodsEditor.ldm_manual) || 0.0,
            ldm: parseFloat(this.goodsEditor.ldm) || 0.0,
            stackable: this.goodsEditor.stackable,
            stacking_factor: parseFloat(this.goodsEditor.stacking_factor) || 1.0,
            gross_weight: parseFloat(this.goodsEditor.gross_weight) || 0.0,
            volumetric_weight: parseFloat(this.goodsEditor.volumetric_weight) || 0.0,
            billable_weight: parseFloat(this.goodsEditor.billable_weight) || 0.0,
            package_type_id: this.goodsEditor.package_type_id,
            is_dangerous_goods: this.goodsEditor.is_dangerous_goods,
            adr_substance_id: this.goodsEditor.adr_substance_id,
            adr_description: this.goodsEditor.adr_description,
            net_explosive_mass: parseFloat(this.goodsEditor.net_explosive_mass) || 0.0,
            adr_limited_quantity: this.goodsEditor.adr_limited_quantity,
            environmentally_hazardous: this.goodsEditor.environmentally_hazardous,
            temperature_min: this.goodsEditor.temperature_min,
            temperature_max: this.goodsEditor.temperature_max,
            material_type_id: this.goodsEditor.material_type_id,
            waste_code: this.goodsEditor.waste_code,
            container_type_id: this.goodsEditor.container_type_id,
            container_number: this.goodsEditor.container_number,
            container_seal_number: this.goodsEditor.container_seal_number,
            container_tare_weight: parseFloat(this.goodsEditor.container_tare_weight) || 0.0,
            volume_liters: parseFloat(this.goodsEditor.volume_liters) || 0.0,
            liquid_density: parseFloat(this.goodsEditor.liquid_density) || 0.0,
            liquid_product_name: this.goodsEditor.liquid_product_name,
            nmfc_class_manual: this.goodsEditor.nmfc_class_manual,
            nmfc_class_id: this.goodsEditor.nmfc_class_id,
        };

        if (this.goodsEditor.idx !== null) {
            this.state.goods_lines[this.goodsEditor.idx] = row;
        } else {
            this.state.goods_lines.push(row);
        }

        this.state.showGoodsEditor = false;
        this.triggerPreview();
    }

    duplicateGoodsRow(idx) {
        const copy = { ...this.state.goods_lines[idx] };
        this.state.goods_lines.push(copy);
        this.triggerPreview();
    }

    deleteGoodsRow(idx) {
        this.state.goods_lines.splice(idx, 1);
        this.triggerPreview();
    }

    // ── Charge Editor ────────────────────────────────────────────────
    onChargeFieldChange(idx, field, val) {
        const row = this.state.charges[idx];
        if (!row) return;

        if (field === 'product_id') {
            const pId = parseInt(val);
            row.product_id = pId;
            const prod = this.state.products.find(p => p.id === pId);
            row.product_name = prod ? prod.name : '';
        } else if (field === 'price_type') {
            row.price_type = val;
        } else if (field === 'quantity') {
            row.quantity = parseFloat(val) || 0.0;
            row.price = row.quantity * row.price_per_unit;
        } else if (field === 'price_per_unit') {
            row.price_per_unit = parseFloat(val) || 0.0;
            row.price = row.quantity * row.price_per_unit;
        }

        row.manually_added = true;
        this.state.is_charges_customized = true;
        this.triggerPreview();
    }

    addBlankCharge() {
        const defaultProduct = this.state.products[0];
        this.state.charges.push({
            product_id: defaultProduct ? defaultProduct.id : null,
            product_name: defaultProduct ? defaultProduct.name : '',
            price_type: 'price_per_order',
            quantity: 1.0,
            price_per_unit: 0.0,
            price: 0.0,
            manually_added: true
        });
        this.state.is_charges_customized = true;
        this.triggerPreview();
    }

    removeChargeRow(idx) {
        this.state.charges.splice(idx, 1);
        this.state.is_charges_customized = true;
        this.triggerPreview();
    }

    recalculateChargesFromContract() {
        this.state.is_charges_customized = false;
        this.triggerPreview();
    }

    setPriority(val) {
        if (this.state.priority === val) {
            this.state.priority = (parseInt(val) - 1).toString();
        } else {
            this.state.priority = val;
        }
        this.triggerPreview();
    }

    toggleRequirement(id) {
        const idx = this.state.requirement_ids.indexOf(id);
        if (idx > -1) {
            this.state.requirement_ids.splice(idx, 1);
        } else {
            this.state.requirement_ids.push(id);
        }
        this.triggerPreview();
    }

    // ── Saving & Actions ─────────────────────────────────────────────
    async onSave(action = "draft") {
        const payload = this.getPayload();

        try {
            const orderId = await this.orm.call(
                "transport.order",
                "create_from_booking",
                [payload]
            );

            if (orderId) {
                this.notification.add(_t("Booking successfully saved!"), { type: "success" });

                if (action === "confirm") {
                    await this.orm.call("transport.order", "action_confirm", [[orderId]]);
                }

                if (action === "close") {
                    this.actionService.doAction("transport_management.action_transport_order");
                } else {
                    this.actionService.doAction({
                        type: "ir.actions.act_window",
                        res_model: "transport.order",
                        res_id: orderId,
                        views: [[false, "form"]],
                        target: "current",
                    });
                }
            }
        } catch (err) {
            this.notification.add(_t("Failed to save booking: ") + (err.message || err), { type: "danger" });
        }
    }

    async onCreateCustomer() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: _t("Create Customer"),
            res_model: "tms.create.customer.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_company_id: this.state.company_id ? parseInt(this.state.company_id) : false,
            }
        }, {
            onClose: async () => {
                await this.loadCustomersForCompany(this.state.company_id);
            }
        });
    }

    async onCreateOrderContact() {
        if (!this.state.customer_id) {
            this.notification.add(_t("Please select a Customer first."), { type: "danger" });
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: _t("Create Contact"),
            res_model: "res.partner",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_parent_id: parseInt(this.state.customer_id),
                default_is_company: false,
            }
        }, {
            onClose: async () => {
                await this.loadContacts(this.state.customer_id);
            }
        });
    }

    onCreateCompany() {
        this.dialogService.add(SelectCreateDialog, {
            resModel: "res.company",
            title: _t("Search: Company"),
            multiSelect: false,
            noCreate: false,
            domain: [],
            context: {},
            onSelected: async (selectedIds) => {
                if (selectedIds && selectedIds.length > 0) {
                    const selectedId = selectedIds[0];
                    this.state.companies = await this.orm.searchRead("res.company", [], ["id", "name"]);
                    this.state.company_id = selectedId;
                    await this.loadCustomersForCompany(selectedId);
                    this.triggerPreview();
                }
            }
        });
    }

    onCreateOrderType() {
        this.dialogService.add(SelectCreateDialog, {
            resModel: "transport.order.type",
            title: _t("Search: Order type"),
            multiSelect: false,
            noCreate: false,
            domain: [],
            context: {},
            onSelected: async (selectedIds) => {
                if (selectedIds && selectedIds.length > 0) {
                    const selectedId = selectedIds[0];
                    this.state.order_types = await this.orm.searchRead("transport.order.type", [], ["id", "name", "goods_profile_id", "default_planning_type"]);
                    this.state.transport_order_type_id = selectedId;
                    
                    const selectedType = this.state.order_types.find(ot => ot.id === selectedId);
                    if (selectedType && selectedType.goods_profile_id) {
                        const profileId = Array.isArray(selectedType.goods_profile_id)
                            ? selectedType.goods_profile_id[0]
                            : selectedType.goods_profile_id;
                        this.state.goods_profile_id = profileId;
                    }
                    this.triggerPreview();
                }
            }
        });
    }

    onCreateFreightService() {
        this.dialogService.add(SelectCreateDialog, {
            resModel: "freight.service",
            title: _t("Search: Freight service"),
            multiSelect: false,
            noCreate: false,
            domain: [],
            context: {},
            onSelected: async (selectedIds) => {
                if (selectedIds && selectedIds.length > 0) {
                    const selectedId = selectedIds[0];
                    this.state.freight_services = await this.orm.searchRead("freight.service", [], ["id", "name"]);
                    this.state.freight_service_id = selectedId;
                    this.triggerPreview();
                }
            }
        });
    }

    async generateWaybillNumber() {
        if (!this.state.company_id) {
            this.notification.add(_t("Company has to be defined in order to generate a new waybill number."), { type: "danger" });
            return;
        }
        try {
            const formData = new FormData();
            formData.append("company_id", this.state.company_id);
            formData.append("csrf_token", odoo.csrf_token);
            
            const response = await fetch("/api/generate_waybill_number", {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            
            if (response.ok && result.waybill_number) {
                this.state.consignment_waybill_number = result.waybill_number;
                this.notification.add(_t("Waybill number generated successfully!"), { type: "success" });
            } else {
                const errorMsg = result.message || _t("Failed to generate waybill number.");
                this.notification.add(errorMsg, { type: "danger" });
            }
        } catch (e) {
            this.notification.add(_t("Error generating waybill number: ") + e, { type: "danger" });
        }
    }

    onSearchAddressBook(type) {
        this.dialogService.add(SelectCreateDialog, {
            resModel: "res.partner",
            title: _t("Search Address"),
            multiSelect: false,
            noCreate: false,
            domain: [],
            context: {},
            onSelected: async (selectedIds) => {
                if (selectedIds && selectedIds.length > 0) {
                    const partnerId = selectedIds[0];
                    const partner = await this.orm.read(
                        "res.partner",
                        [partnerId],
                        ["name", "street", "street2", "city", "zip", "country_id", "state_id", "partner_latitude", "partner_longitude", "phone", "mobile", "email", "access_instructions"]
                    );
                    if (partner && partner.length > 0) {
                        this.onPickAddress(type, partner[0]);
                    }
                }
            }
        });
    }

    onCreateNewPartner(type) {
        const name = this.state[type + "_name"] || "";
        if (!name.trim()) {
            this.notification.add(_t("Please fill in the Name field first to save this address."), { type: "warning" });
            return;
        }
        if (!this.state.customer_id) {
            this.notification.add(_t("Please select a Customer first."), { type: "warning" });
            return;
        }

        this.dialogService.add(ConfirmationDialog, {
            body: _t("Save this address to the customer's address book?"),
            confirm: async () => {
                try {
                    const vals = {
                        name: this.state[type + "_name"],
                        street: this.state[type + "_street"],
                        street2: this.state[type + "_street_2"],
                        city: this.state[type + "_city"],
                        zip: this.state[type + "_zip"],
                        state_id: this.state[type + "_state_id"] ? parseInt(this.state[type + "_state_id"]) : false,
                        country_id: this.state[type + "_country_id"] ? parseInt(this.state[type + "_country_id"]) : false,
                        partner_latitude: parseFloat(this.state[type + "_latitude"] || 0.0),
                        partner_longitude: parseFloat(this.state[type + "_longitude"] || 0.0),
                        phone: this.state[type + "_phone"],
                        mobile: this.state[type + "_mobile"],
                        email: this.state[type + "_email"],
                        access_instructions: this.state[type + "_access_instructions"],
                        parent_id: parseInt(this.state.customer_id),
                        is_company: false,
                        type: "delivery",
                    };
                    const partnerIds = await this.orm.create("res.partner", [vals]);
                    if (partnerIds && partnerIds.length > 0) {
                        const partnerId = partnerIds[0];
                        this.state[type + "_address_id"] = partnerId;
                        this.notification.add(_t("Address successfully saved to address book!"), { type: "success" });
                        this.triggerPreview();
                    }
                } catch (err) {
                    this.notification.add(_t("Failed to save address: ") + err, { type: "danger" });
                }
            },
            cancel: () => {},
        });
    }

    onSelectLocationOnMap(type) {
        this.state.map_picking_mode = type;
        this.notification.add(_t("Map Picking Mode Active. Please click anywhere on the map to set coordinates."), { type: "warning" });
        if (this.mapContainer.el) {
            this.mapContainer.el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    }

    async onGeocodeAddress(type) {
        const street = this.state[type + "_street"] || "";
        const city = this.state[type + "_city"] || "";
        const countryId = this.state[type + "_country_id"];
        let countryName = "";
        if (countryId) {
            const country = this.state.countries.find(c => c.id === parseInt(countryId));
            if (country) countryName = country.display_name;
        }

        const query = [street, city, countryName].filter(Boolean).join(", ");
        if (!query) {
            this.notification.add(_t("Please fill in the street/city/country first to search coordinates."), { type: "warning" });
            return;
        }

        try {
            const res = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=1`);
            const data = await res.json();
            if (data && data.length > 0) {
                const lat = parseFloat(data[0].lat).toFixed(6);
                const lng = parseFloat(data[0].lon).toFixed(6);
                this.state[type + "_latitude"] = lat;
                this.state[type + "_longitude"] = lng;
                this.notification.add(_t("Coordinates successfully resolved!"), { type: "success" });
                this.updateMapRoute();
                this.triggerPreview();
            } else {
                this.notification.add(_t("Address not found on map. Please adjust spelling or coordinates."), { type: "danger" });
            }
        } catch (err) {
            this.notification.add(_t("Failed to resolve coordinates: ") + err, { type: "danger" });
        }
    }

    async openImportAddressModal(type) {
        this.state.showImportAddressModal = type;
        this.state.importSearchQuery = "";
        this.state.addressBookResults = [];
        this.state.oftenUsedAddresses = [];
        this.state.transportHubs = [];

        if (this.state.customer_id) {
            try {
                const usages = await this.orm.searchRead(
                    "transport.address.usage",
                    [["customer_id", "=", parseInt(this.state.customer_id)]],
                    ["address_id"],
                    { limit: 15 }
                );
                const addressIds = [...new Set(usages.map(u => u.address_id[0]).filter(Boolean))];
                if (addressIds.length > 0) {
                    this.state.oftenUsedAddresses = await this.orm.read(
                        "res.partner",
                        addressIds,
                        ["name", "street", "street2", "city", "zip", "country_id", "state_id", "partner_latitude", "partner_longitude", "phone", "mobile", "email", "access_instructions"]
                    );
                }
            } catch (e) {
                console.error("Failed to load often used addresses: ", e);
            }
        }

        try {
            const hubs = await this.orm.searchRead(
                "transport.hub",
                [],
                ["partner_id"],
                { limit: 15 }
            );
            const hubPartnerIds = [...new Set(hubs.map(h => h.partner_id[0]).filter(Boolean))];
            if (hubPartnerIds.length > 0) {
                this.state.transportHubs = await this.orm.read(
                    "res.partner",
                    hubPartnerIds,
                    ["name", "street", "street2", "city", "zip", "country_id", "state_id", "partner_latitude", "partner_longitude", "phone", "mobile", "email", "access_instructions"]
                );
            }
        } catch (e) {
            console.error("Failed to load transport hubs: ", e);
        }
    }

    async onImportSearch(val) {
        this.state.importSearchQuery = val;
        if (!val || val.length < 2) {
            this.state.addressBookResults = [];
            return;
        }
        try {
            this.state.addressBookResults = await this.orm.searchRead(
                "res.partner",
                ["|", "|", ["name", "ilike", val], ["city", "ilike", val], ["zip", "ilike", val]],
                ["name", "street", "street2", "city", "zip", "country_id", "state_id", "partner_latitude", "partner_longitude", "phone", "mobile", "email", "access_instructions"],
                { limit: 20 }
            );
        } catch (e) {
            console.error("Import search failed: ", e);
        }
    }

    onSelectImportAddress(partner) {
        const type = this.state.showImportAddressModal;
        if (type && partner) {
            this.onPickAddress(type, partner);
        }
        this.state.showImportAddressModal = null;
    }
}

registry.category("actions").add("transport_management_new.owl_order_registration", OwlOrderRegistration);
