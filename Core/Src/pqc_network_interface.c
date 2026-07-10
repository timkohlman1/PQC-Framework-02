#include "pqc_network_interface.h"

#include "lwip/ip4_addr.h"
#include "lwip/netif.h"

#include <stdio.h>
#include <string.h>

/*
 * Phase M6.2 project-owned network-interface boundary.
 *
 * The local lwIP netif is deliberately left unattached. No driver callbacks
 * are installed, netif registration is not performed, and no ST67W61M1, DHCP, TCP, TLS,
 * or MQTT operation is attempted. Status is refreshed from the actual lwIP
 * netif flags and IPv4 storage rather than from a fixed status record.
 */

static struct netif s_pqc_unavailable_netif;

static PQC_NetworkAvailability availability_from_bool(bool available)
{
  return available ? PQC_NETWORK_AVAILABILITY_AVAILABLE
                   : PQC_NETWORK_AVAILABILITY_UNAVAILABLE;
}

static const char *availability_name(PQC_NetworkAvailability availability)
{
  return (availability == PQC_NETWORK_AVAILABILITY_AVAILABLE) ? "available"
                                                               : "unavailable";
}

void PQC_NetworkInterface_Init(void)
{
  memset(&s_pqc_unavailable_netif, 0, sizeof(s_pqc_unavailable_netif));
  s_pqc_unavailable_netif.name[0] = 'p';
  s_pqc_unavailable_netif.name[1] = 'q';

/*
   * memset() leaves the unattached lwIP netif with zero flags and an
   * unspecified IPv4 address. Avoid the lwIP address-update API here because
   * it is intended for an initialized core/netif path and pulls timeout and
   * reporting code that requires the platform time hook.
   */
}

PQC_NetworkInterfaceStatus PQC_NetworkInterface_GetStatus(void)
{
  PQC_NetworkInterfaceStatus status;
  const bool netif_up = netif_is_up(&s_pqc_unavailable_netif) != 0;
  const bool link_up = netif_is_link_up(&s_pqc_unavailable_netif) != 0;
#if LWIP_IPV4
  const bool ipv4_any = ip4_addr_isany_val(*netif_ip4_addr(&s_pqc_unavailable_netif)) != 0;
#else
  const bool ipv4_any = true;
#endif
  const bool ip_available = netif_up && !ipv4_any;
  const bool tcp_ready = netif_up && link_up && ip_available;
  const bool transport_available = false;

  status.schema_version = PQC_NETWORK_INTERFACE_SCHEMA_VERSION;
  status.boundary_present = true;
  status.lwip_netif_up = netif_up;
  status.lwip_link_up = link_up;
  status.lwip_ipv4_any = ipv4_any;
  status.link = availability_from_bool(link_up);
  status.ip_address = availability_from_bool(ip_available);
  status.tcp_ready = availability_from_bool(tcp_ready);
  status.transport = availability_from_bool(transport_available);

  return status;
}

const char *PQC_NetworkInterface_BackendName(void)
{
  return "unavailable";
}

const char *PQC_NetworkInterface_UnavailableReason(void)
{
  return "ST67W61M1-backed lwIP netif bring-up is deferred";
}

bool PQC_NetworkInterface_StatusLine(char *buffer, uint32_t buffer_length)
{
  char ipv4_text[IP4ADDR_STRLEN_MAX];
  const char *ipv4_result = NULL;
  const PQC_NetworkInterfaceStatus status = PQC_NetworkInterface_GetStatus();

  if ((buffer == NULL) || (buffer_length == 0U))
  {
    return false;
  }

#if LWIP_IPV4
  ipv4_result = ip4addr_ntoa_r(
      netif_ip4_addr(&s_pqc_unavailable_netif),
      ipv4_text,
      (int)sizeof(ipv4_text));
#else
  (void)ipv4_text;
#endif

  if (ipv4_result == NULL)
  {
    ipv4_result = "unavailable";
  }

  const int written = snprintf(
      buffer,
      (size_t)buffer_length,
      "lwIP network interface: evidence=lwip-netif-state-only backend=%s boundary=%s lwip_netif_up=%u lwip_link_up=%u lwip_ipv4_any=%u lwip_ipv4=%s link=%s ip=%s tcp=%s transport=%s wifi_module=unavailable st67w61m1=unavailable tls_handshake=unavailable mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable end_to_end=unavailable\r\n",
      PQC_NetworkInterface_BackendName(),
      status.boundary_present ? "present" : "absent",
      status.lwip_netif_up ? 1U : 0U,
      status.lwip_link_up ? 1U : 0U,
      status.lwip_ipv4_any ? 1U : 0U,
      ipv4_result,
      availability_name(status.link),
      availability_name(status.ip_address),
      availability_name(status.tcp_ready),
      availability_name(status.transport));

  if ((written < 0) || ((uint32_t)written >= buffer_length))
  {
    buffer[0] = '\0';
    return false;
  }

  return true;
}
