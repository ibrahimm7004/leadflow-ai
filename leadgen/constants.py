from __future__ import annotations

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PAGE_SIZE = 20
LEADS_TAB_NAME = "Leads"
DETAILS_TAB_NAME = "Details"

EXCLUDED_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "linkedin.com",
    "pinterest.com",
    "yelp.com",
    "linktr.ee",
    "beacons.ai",
    "carrd.co",
    "app.thecut.co",
}

EXTERNAL_PLATFORM_DOMAINS = {
    "acuityscheduling.com",
    "appointments.squareup.com",
    "booksy.com",
    "calendly.com",
    "exploretock.com",
    "fresha.com",
    "glossgenius.com",
    "instagram.com",
    "linktr.ee",
    "mangomint.com",
    "mindbody.io",
    "mindbodyonline.com",
    "my.canva.site",
    "opentable.com",
    "resy.com",
    "schedulicity.com",
    "setmore.com",
    "square.site",
    "styleseat.com",
    "thecut.co",
    "toasttab.com",
    "vagaro.com",
    "wixsite.com",
    "zenoti.com",
}

EXTERNAL_PLATFORM_DOMAIN_MAP = {
    "acuityscheduling.com": "acuity",
    "appointments.squareup.com": "square_appointments",
    "booksy.com": "booksy",
    "calendly.com": "calendly",
    "exploretock.com": "tock",
    "fresha.com": "fresha",
    "glossgenius.com": "glossgenius",
    "mangomint.com": "mangomint",
    "mindbody.io": "mindbody",
    "mindbodyonline.com": "mindbody",
    "opentable.com": "opentable",
    "resy.com": "resy",
    "schedulicity.com": "schedulicity",
    "setmore.com": "setmore",
    "square.site": "square_site",
    "styleseat.com": "styleseat",
    "thecut.co": "thecut",
    "toasttab.com": "toasttab",
    "vagaro.com": "vagaro",
    "wixsite.com": "wixsite",
    "zenoti.com": "zenoti",
}

SOCIAL_DOMAIN_MAP = {
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "tiktok.com": "tiktok",
    "x.com": "x",
    "twitter.com": "twitter",
    "youtube.com": "youtube",
    "linkedin.com": "linkedin",
    "pinterest.com": "pinterest",
}

SUBDOMAIN_ONLY = {"squarespace.com", "wixsite.com"}

FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.nationalPhoneNumber,"
    "places.websiteUri,"
    "places.rating,"
    "places.userRatingCount,"
    "places.googleMapsUri,"
    "places.accessibilityOptions,"
    "places.addressComponents,"
    "places.addressDescriptor,"
    "places.adrFormatAddress,"
    "places.businessStatus,"
    "places.containingPlaces,"
    "places.googleMapsLinks,"
    "places.iconBackgroundColor,"
    "places.iconMaskBaseUri,"
    "places.location,"
    "places.photos,"
    "places.plusCode,"
    "places.postalAddress,"
    "places.primaryType,"
    "places.primaryTypeDisplayName,"
    "places.pureServiceAreaBusiness,"
    "places.shortFormattedAddress,"
    "places.subDestinations,"
    "places.types,"
    "places.utcOffsetMinutes,"
    "places.viewport,"
    "places.currentOpeningHours,"
    "places.currentSecondaryOpeningHours,"
    "places.internationalPhoneNumber,"
    "places.priceLevel,"
    "places.priceRange,"
    "places.regularOpeningHours,"
    "places.regularSecondaryOpeningHours,"
    "places.name,"
    "places.attributions,"
    "nextPageToken"
)

OUTPUT_FIELDS = [
    "name",
    "phone",
    "address",
    "websiteUri",
    "rating",
    "userRatingCount",
    "googleMapsUri",
    "accessibilityOptions",
    "addressComponents",
    "addressDescriptor",
    "adrFormatAddress",
    "businessStatus",
    "containingPlaces",
    "googleMapsLinks",
    "iconBackgroundColor",
    "iconMaskBaseUri",
    "location",
    "photos",
    "plusCode",
    "postalAddress",
    "primaryType",
    "primaryTypeDisplayName",
    "pureServiceAreaBusiness",
    "shortFormattedAddress",
    "subDestinations",
    "types",
    "utcOffsetMinutes",
    "viewport",
    "currentOpeningHours",
    "currentSecondaryOpeningHours",
    "internationalPhoneNumber",
    "priceLevel",
    "priceRange",
    "regularOpeningHours",
    "regularSecondaryOpeningHours",
    "placeName",
    "attributions",
    "placeId",
]

LEADS_FIELDS = [
    "score",
    "name",
    "phone",
    "address",
    "websiteUri",
    "rating",
    "userRatingCount",
    "googleMapsUri",
    "photos",
    "primaryType",
    "regularOpeningHours",
]
